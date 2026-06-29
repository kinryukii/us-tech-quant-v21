from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR"
OUT = ROOT / "outputs" / "v21" / STAGE

BASE = ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER"
BASE_LEDGER = BASE / "switch_state_forward_ledger.csv"
BASE_PENDING = BASE / "switch_state_pending_maturity.csv"
BASE_MATURED = BASE / "switch_state_matured_results.csv"
BASE_SUMMARY = BASE / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER_summary.json"

SWITCH_SUMMARY = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER_summary.json"
A1_RANK = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2_RANK = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_full.csv"
AI_RANK = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_full.csv"
E_R1_TOP20 = ROOT / "outputs" / "v21" / "V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR" / "e_r1_top20.csv"
SOFTCAP_PORT = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "softcap_filter_variant_portfolios.csv"
PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

STATES = [
    "A1_CONTROL",
    "C_R2_CHALLENGER",
    "AI_BOTTLENECK_THEME",
    "A1_PLUS_C_R2_FORWARD_TRACKING",
    "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
    "A1_PLUS_E_R1_DEFENSIVE_STANDBY",
    "A1_PLUS_SOFTCAP_WATCH_ONLY",
]
HORIZONS = [5, 10, 20]
POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "switch_adoption_allowed": False,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


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
            rel = path.relative_to(ROOT).as_posix().lower().replace("-", "_")
            protected = any(token in rel for token in ["broker", "real_book", "realbook"])
            protected = protected or ("official" in rel and any(k in rel for k in ["rank", "weight", "allocation", "recommend"]))
            if protected:
                hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    return hashes


def norm_ticker(df: pd.DataFrame, col: str = "ticker") -> pd.DataFrame:
    out = df.copy()
    if col in out.columns:
        out[col] = out[col].astype(str).str.upper().str.strip()
    return out


def latest_date_from_rank(*frames: pd.DataFrame) -> str:
    dates = []
    for df in frames:
        for col in ["latest_price_date_used", "latest_price_date", "ranking_date", "as_of_date"]:
            if col in df.columns:
                d = pd.to_datetime(df[col], errors="coerce").dropna()
                if not d.empty:
                    dates.append(d.max())
    return str(max(dates).date()) if dates else ""


def top_equal_weight(df: pd.DataFrame, ticker_col: str = "ticker", limit: int = 20) -> pd.DataFrame:
    if df.empty or ticker_col not in df.columns:
        return pd.DataFrame(columns=["ticker", "component_weight"])
    out = df.copy()
    out[ticker_col] = out[ticker_col].astype(str).str.upper().str.strip()
    if "rank" in out.columns:
        out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
        out = out.sort_values(["rank", ticker_col])
    out = out[out[ticker_col].ne("")].drop_duplicates(ticker_col).head(limit)
    if out.empty:
        return pd.DataFrame(columns=["ticker", "component_weight"])
    return pd.DataFrame({"ticker": out[ticker_col].tolist(), "component_weight": 1.0 / len(out)})


def softcap_weight() -> pd.DataFrame:
    df = read_csv(SOFTCAP_PORT)
    if df.empty or "ticker" not in df.columns:
        return pd.DataFrame(columns=["ticker", "component_weight"])
    d = norm_ticker(df)
    if "portfolio_bucket" in d.columns:
        d = d[d["portfolio_bucket"].astype(str).eq("Top20")]
    if "filter_variant" in d.columns and d["filter_variant"].astype(str).eq("SOFTCAP_FILTERED").any():
        d = d[d["filter_variant"].astype(str).eq("SOFTCAP_FILTERED")]
    elif "filter_variant" in d.columns and d["filter_variant"].astype(str).eq("SOFTCAP_RAW").any():
        d = d[d["filter_variant"].astype(str).eq("SOFTCAP_RAW")]
    weight_col = "final_filter_weight" if "final_filter_weight" in d.columns else "softcap_weight" if "softcap_weight" in d.columns else ""
    if not weight_col:
        return pd.DataFrame(columns=["ticker", "component_weight"])
    d["component_weight"] = pd.to_numeric(d[weight_col], errors="coerce")
    d = d.dropna(subset=["component_weight"]).drop_duplicates("ticker").head(20)
    total = d["component_weight"].sum()
    if total <= 0:
        return pd.DataFrame(columns=["ticker", "component_weight"])
    d["component_weight"] = d["component_weight"] / total
    return d[["ticker", "component_weight"]]


def combine(parts: list[tuple[str, pd.DataFrame, float]]) -> pd.DataFrame:
    rows = []
    for name, frame, sleeve_weight in parts:
        if frame.empty or sleeve_weight <= 0:
            continue
        f = frame.copy()
        f["state_component"] = name
        f["state_weight"] = f["component_weight"] * sleeve_weight
        rows.append(f[["ticker", "state_component", "state_weight"]])
    if not rows:
        return pd.DataFrame(columns=["ticker", "state_component", "state_weight"])
    out = pd.concat(rows, ignore_index=True).groupby(["ticker", "state_component"], as_index=False)["state_weight"].sum()
    total = out["state_weight"].sum()
    if total > 0:
        out["state_weight"] = out["state_weight"] / total
    return out


def state_holdings() -> dict[str, pd.DataFrame]:
    a1 = top_equal_weight(norm_ticker(read_csv(A1_RANK)))
    c2 = top_equal_weight(norm_ticker(read_csv(C_R2_RANK)))
    ai = top_equal_weight(norm_ticker(read_csv(AI_RANK)))
    e = read_csv(E_R1_TOP20)
    e_col = "ticker_norm" if "ticker_norm" in e.columns else "ticker"
    e1 = top_equal_weight(e, e_col)
    soft = softcap_weight()
    return {
        "A1_CONTROL": combine([("A1", a1, 1.0)]),
        "C_R2_CHALLENGER": combine([("C_R2", c2, 1.0)]),
        "AI_BOTTLENECK_THEME": combine([("AI_BOTTLENECK", ai, 1.0)]),
        "A1_PLUS_C_R2_FORWARD_TRACKING": combine([("A1", a1, 0.70), ("C_R2", c2, 0.30)]),
        "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING": combine([("A1", a1, 0.60), ("C_R2", c2, 0.25), ("AI_BOTTLENECK", ai, 0.15)]),
        "A1_PLUS_E_R1_DEFENSIVE_STANDBY": combine([("A1", a1, 0.70), ("E_R1", e1, 0.30)]),
        "A1_PLUS_SOFTCAP_WATCH_ONLY": combine([("SOFTCAP", soft, 1.0)]),
    }


def price_panel() -> pd.DataFrame:
    p = read_csv(PRICE)
    if p.empty:
        return p
    p["ticker"] = p["symbol"].astype(str).str.upper().str.strip()
    p["date"] = pd.to_datetime(p["date"], errors="coerce")
    p["adjusted_close"] = pd.to_numeric(p["adjusted_close"], errors="coerce")
    return p.dropna(subset=["ticker", "date", "adjusted_close"]).sort_values(["ticker", "date"])


def ticker_forward_return(prices: pd.DataFrame, ticker: str, ranking_date: str, horizon: int) -> tuple[float | None, str]:
    if prices.empty or not ranking_date:
        return None, "PRICE_DATA_UNAVAILABLE"
    d0 = pd.to_datetime(ranking_date)
    s = prices[prices["ticker"].eq(ticker)].sort_values("date")
    if s.empty:
        return None, "PRICE_DATA_UNAVAILABLE"
    start = s[s["date"].le(d0)].tail(1)
    if start.empty:
        return None, "PRICE_DATA_UNAVAILABLE"
    future = s[s["date"].gt(start["date"].iloc[0])]
    if len(future) < horizon:
        return None, "PENDING_MATURITY"
    end = future.iloc[horizon - 1]
    if pd.isna(end["adjusted_close"]) or pd.isna(start["adjusted_close"].iloc[0]):
        return None, "PRICE_DATA_UNAVAILABLE"
    return float(end["adjusted_close"] / start["adjusted_close"].iloc[0] - 1.0), "MATURED"


def state_forward_return(holdings: pd.DataFrame, prices: pd.DataFrame, ranking_date: str, horizon: int) -> tuple[float | None, str, int, int]:
    if holdings.empty:
        return None, "INVALID_HOLDINGS", 0, 0
    vals = []
    pending = 0
    valid = 0
    unavailable = 0
    for _, row in holdings.iterrows():
        ret, status = ticker_forward_return(prices, row["ticker"], ranking_date, horizon)
        if ret is None:
            if status == "PENDING_MATURITY":
                pending += 1
            else:
                unavailable += 1
            continue
        valid += 1
        vals.append(float(row["state_weight"]) * ret)
    if valid == 0:
        return None, "PENDING_MATURITY" if pending else "PRICE_DATA_UNAVAILABLE", valid, pending + unavailable
    return float(sum(vals)), "MATURED", valid, pending + unavailable


def append_rows_for_date(ranking_date: str, latest_price: str, existing: pd.DataFrame) -> pd.DataFrame:
    keys = set(zip(existing.get("ranking_date", []), existing.get("tracked_state", []), existing.get("horizon", [])))
    rows = []
    for state in STATES:
        for h in HORIZONS:
            key = (ranking_date, state, f"{h}D")
            if key in keys:
                continue
            rows.append({
                "ranking_date": ranking_date,
                "latest_price_date_used": latest_price,
                "tracked_state": state,
                "horizon": f"{h}D",
                "maturity_status": "PENDING_MATURITY",
                "forward_return": "",
                "valid_return_count": 0,
                "pending_return_count": "",
                "valid_holdings_count": "",
                "state_notes": "APPENDED_BY_R1_DAILY_MONITOR",
                "research_only": True,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "live_trading_allowed": False,
            })
    return pd.DataFrame(rows)


def update_maturity(ledger: pd.DataFrame, holdings_by_state: dict[str, pd.DataFrame], prices: pd.DataFrame, latest_price: str) -> tuple[pd.DataFrame, int]:
    out = ledger.copy()
    for col in ["forward_return", "latest_price_date_used", "maturity_status", "state_notes"]:
        if col in out.columns:
            out[col] = out[col].astype(object)
    newly = 0
    for idx, row in out.iterrows():
        if str(row.get("maturity_status")) == "MATURED":
            continue
        state = str(row["tracked_state"])
        horizon = int(str(row["horizon"]).replace("D", ""))
        ranking_date = str(row["ranking_date"])
        holdings = holdings_by_state.get(state, pd.DataFrame())
        ret, status, valid, pending = state_forward_return(holdings, prices, ranking_date, horizon)
        old = str(row.get("maturity_status", ""))
        out.at[idx, "latest_price_date_used"] = latest_price
        out.at[idx, "maturity_status"] = status
        out.at[idx, "forward_return"] = "" if ret is None else ret
        out.at[idx, "valid_return_count"] = valid
        out.at[idx, "pending_return_count"] = pending
        out.at[idx, "valid_holdings_count"] = int(holdings["ticker"].nunique()) if not holdings.empty else 0
        out.at[idx, "research_only"] = True
        out.at[idx, "official_adoption_allowed"] = False
        out.at[idx, "broker_action_allowed"] = False
        out.at[idx, "live_trading_allowed"] = False
        if old != "MATURED" and status == "MATURED":
            newly += 1
    return out, newly


def vs_a1(matured: pd.DataFrame) -> pd.DataFrame:
    cols = ["ranking_date", "tracked_state", "horizon", "forward_return", "a1_forward_return", "excess_return_vs_a1", "win_vs_a1", "research_only"]
    if matured.empty:
        return pd.DataFrame(columns=cols)
    a1 = matured[matured["tracked_state"].eq("A1_CONTROL")][["ranking_date", "horizon", "forward_return"]].rename(columns={"forward_return": "a1_forward_return"})
    comp = matured.merge(a1, on=["ranking_date", "horizon"], how="left")
    comp["forward_return"] = pd.to_numeric(comp["forward_return"], errors="coerce")
    comp["a1_forward_return"] = pd.to_numeric(comp["a1_forward_return"], errors="coerce")
    comp["excess_return_vs_a1"] = comp["forward_return"] - comp["a1_forward_return"]
    comp["win_vs_a1"] = comp["excess_return_vs_a1"] > 0
    comp["research_only"] = True
    return comp[cols]


def excluded_impact(prices: pd.DataFrame, latest_ranking_date: str) -> pd.DataFrame:
    rows = []
    for ticker in ["HOOD", "WING", "JHX", "AMC"]:
        for h in HORIZONS:
            ret, status = ticker_forward_return(prices, ticker, latest_ranking_date, h)
            rows.append({
                "ticker": ticker,
                "ranking_date": latest_ranking_date,
                "horizon": f"{h}D",
                "maturity_status": status,
                "return_available": ret is not None,
                "excluded_name_forward_return": "" if ret is None else ret,
                "excluded_from_ai_sleeve": True,
                "helped_or_hurt_ai_vs_c_r2": "PENDING_MATURITY" if ret is None else "AVAILABLE_FOR_COMPARISON",
                "research_only": True,
            })
    return pd.DataFrame(rows)


def run_stage() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    warnings: list[dict[str, str]] = []
    base_summary = read_json(BASE_SUMMARY)
    switch_summary = read_json(SWITCH_SUMMARY)
    ledger = read_csv(BASE_LEDGER)
    if ledger.empty:
        ledger = pd.DataFrame(columns=[
            "ranking_date", "latest_price_date_used", "tracked_state", "horizon", "maturity_status",
            "forward_return", "valid_return_count", "pending_return_count", "valid_holdings_count",
            "state_notes", "research_only", "official_adoption_allowed", "broker_action_allowed", "live_trading_allowed",
        ])
    existing_ledger_row_count = len(ledger)
    pending_before = int(ledger["maturity_status"].astype(str).eq("PENDING_MATURITY").sum()) if "maturity_status" in ledger.columns else 0
    matured_before = int(ledger["maturity_status"].astype(str).eq("MATURED").sum()) if "maturity_status" in ledger.columns else 0

    prices = price_panel()
    latest_price = str(prices["date"].max().date()) if not prices.empty else ""
    a1 = norm_ticker(read_csv(A1_RANK))
    c2 = norm_ticker(read_csv(C_R2_RANK))
    ai = norm_ticker(read_csv(AI_RANK))
    latest_ranking_date = latest_date_from_rank(a1, c2, ai) or str(base_summary.get("ranking_date") or switch_summary.get("latest_price_date_used") or "")
    holdings = state_holdings()

    appended = append_rows_for_date(latest_ranking_date, latest_price, ledger)
    new_rows_appended_count = len(appended)
    full = pd.concat([ledger, appended], ignore_index=True) if not appended.empty else ledger.copy()
    before_dedup = len(full)
    full = full.drop_duplicates(["ranking_date", "tracked_state", "horizon"], keep="last")
    deduped = before_dedup - len(full)
    full, newly_matured = update_maturity(full, holdings, prices, latest_price)
    full = full.sort_values(["ranking_date", "tracked_state", "horizon"]).reset_index(drop=True)
    full.to_csv(OUT / "switch_ledger_r1_full_ledger.csv", index=False)
    pending = full[full["maturity_status"].astype(str).eq("PENDING_MATURITY")].copy()
    matured = full[full["maturity_status"].astype(str).eq("MATURED")].copy()
    pending.to_csv(OUT / "switch_ledger_r1_pending_maturity.csv", index=False)
    matured.to_csv(OUT / "switch_ledger_r1_matured_results.csv", index=False)
    comp = vs_a1(matured)
    comp.to_csv(OUT / "switch_ledger_r1_vs_a1_comparison.csv", index=False)
    appended.to_csv(OUT / "switch_ledger_r1_new_rows_appended.csv", index=False)
    pd.DataFrame([{
        "existing_ledger_row_count": existing_ledger_row_count,
        "row_count_before_dedup": before_dedup,
        "row_count_after_dedup": len(full),
        "deduplicated_row_count": deduped,
        "deduplication_key": "ranking_date|tracked_state|horizon",
        "research_only": True,
    }]).to_csv(OUT / "switch_ledger_r1_deduplication_report.csv", index=False)
    by_h = full.groupby(["horizon", "maturity_status"], as_index=False).size().rename(columns={"size": "row_count"})
    by_h.to_csv(OUT / "switch_ledger_r1_maturity_status_by_horizon.csv", index=False)
    impact = excluded_impact(prices, latest_ranking_date)
    impact.to_csv(OUT / "switch_ledger_r1_excluded_name_impact.csv", index=False)

    if newly_matured == 0:
        warnings.append({"warning_type": "NO_NEW_MATURED_ROWS", "warning": "No pending switch-state rows matured with the current price panel."})
    if new_rows_appended_count == 0:
        warnings.append({"warning_type": "NO_NEW_RANKING_DATE", "warning": "Latest ranking date already exists; maturity update only."})
    if prices.empty:
        warnings.append({"warning_type": "PRICE_PANEL_MISSING", "warning": "Price panel unavailable."})
    warn_df = pd.DataFrame(warnings) if warnings else pd.DataFrame([{"warning_type": "NONE", "warning": ""}])
    warn_df.to_csv(OUT / "switch_ledger_r1_data_quality_warnings.csv", index=False)

    after = protected_hashes()
    protected_modified = before != after
    pending_after = int(full["maturity_status"].astype(str).eq("PENDING_MATURITY").sum())
    matured_after = int(full["maturity_status"].astype(str).eq("MATURED").sum())
    if protected_modified:
        final_status = "FAIL_V21_164_R1_SWITCH_LEDGER_SCRIPT_ERROR"
    elif newly_matured > 0:
        final_status = "PASS_V21_164_R1_SWITCH_LEDGER_UPDATED_WITH_MATURED_RESULTS"
    elif new_rows_appended_count == 0 and newly_matured == 0:
        final_status = "WARN_V21_164_R1_SWITCH_LEDGER_NO_NEW_DATA"
    else:
        final_status = "PARTIAL_PASS_V21_164_R1_SWITCH_LEDGER_UPDATED_WAIT_MATURITY"
    summary = {
        "final_status": final_status,
        "decision": "SWITCH_LEDGER_MATURITY_MONITOR_ACTIVE_WAIT_RESULTS",
        **{**POLICY, "protected_outputs_modified": protected_modified},
        "latest_price_date_used": latest_price,
        "latest_ranking_date_seen": latest_ranking_date,
        "existing_ledger_row_count": existing_ledger_row_count,
        "new_rows_appended_count": new_rows_appended_count,
        "deduplicated_row_count": deduped,
        "pending_maturity_count_before": pending_before,
        "pending_maturity_count_after": pending_after,
        "matured_result_count_before": matured_before,
        "matured_result_count_after": matured_after,
        "newly_matured_count": newly_matured,
        "horizons": [f"{h}D" for h in HORIZONS],
        "selected_switch_state": str(switch_summary.get("selected_switch_state", base_summary.get("selected_switch_state", ""))),
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    write_json(OUT / f"{STAGE}_summary.json", summary)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={summary['decision']}",
        f"latest_price_date_used={latest_price}",
        f"latest_ranking_date_seen={latest_ranking_date}",
        f"existing_ledger_row_count={existing_ledger_row_count}",
        f"new_rows_appended_count={new_rows_appended_count}",
        f"newly_matured_count={newly_matured}",
        f"pending_maturity_before_after={pending_before}->{pending_after}",
        f"matured_results_before_after={matured_before}->{matured_after}",
        "maturity_status_by_horizon=" + by_h.to_json(orient="records"),
        "available_vs_a1_comparisons=" + ("none" if comp.empty else comp.head(10).to_json(orient="records")),
        "excluded_name_impact=" + impact.to_json(orient="records"),
        f"warnings={len(warnings)}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
    ]
    (OUT / f"{STAGE}_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    try:
        summary = run_stage()
    except Exception as exc:  # pragma: no cover
        OUT.mkdir(parents=True, exist_ok=True)
        summary = {
            "final_status": "FAIL_V21_164_R1_SWITCH_LEDGER_SCRIPT_ERROR",
            "decision": "SWITCH_LEDGER_MATURITY_MONITOR_ACTIVE_WAIT_RESULTS",
            **POLICY,
            "error": str(exc),
            "warning_count": 1,
        }
        write_json(OUT / f"{STAGE}_summary.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not str(summary.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
