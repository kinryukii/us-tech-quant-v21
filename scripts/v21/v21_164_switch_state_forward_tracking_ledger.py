from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER"
OUT = ROOT / "outputs" / "v21" / STAGE

SWITCH_SUMMARY = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER_summary.json"
SWITCH_STATE = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_state.csv"
A1_RANK = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2_RANK = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_full.csv"
AI_RANK = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_full.csv"
AI_CONC = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_subtheme_concentration.csv"
AI_WARN = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_data_quality_warnings.csv"
AI_EXCLUDED = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_non_eligible_c_r2_top20.csv"
E_R1_TOP20 = ROOT / "outputs" / "v21" / "V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR" / "e_r1_top20.csv"
SOFTCAP_PORT = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "softcap_filter_variant_portfolios.csv"
PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
META = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_CACHE.csv"

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
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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


def combine_components(parts: list[tuple[str, pd.DataFrame, float]]) -> tuple[pd.DataFrame, dict[str, float], str]:
    rows = []
    component_availability = {}
    notes = []
    for name, frame, sleeve_weight in parts:
        available = not frame.empty and sleeve_weight > 0
        component_availability[name] = sleeve_weight if available else 0.0
        if not available:
            notes.append(f"{name}_UNAVAILABLE")
            continue
        f = frame.copy()
        f["state_component"] = name
        f["state_weight"] = f["component_weight"] * sleeve_weight
        rows.append(f[["ticker", "state_component", "state_weight"]])
    if not rows:
        return pd.DataFrame(columns=["ticker", "state_component", "state_weight"]), component_availability, "|".join(notes)
    out = pd.concat(rows, ignore_index=True)
    out = out.groupby(["ticker", "state_component"], as_index=False)["state_weight"].sum()
    total = out["state_weight"].sum()
    if total > 0:
        out["state_weight"] = out["state_weight"] / total
    return out, component_availability, "|".join(notes)


def price_panel() -> pd.DataFrame:
    p = read_csv(PRICE)
    if p.empty:
        return p
    p["ticker"] = p["symbol"].astype(str).str.upper().str.strip()
    p["date"] = pd.to_datetime(p["date"], errors="coerce")
    p["adjusted_close"] = pd.to_numeric(p["adjusted_close"], errors="coerce")
    return p.dropna(subset=["ticker", "date", "adjusted_close"]).sort_values(["ticker", "date"])


def ticker_forward_return(prices: pd.DataFrame, ticker: str, ranking_date: str, horizon: int) -> tuple[float | None, str, str, str]:
    if prices.empty or not ranking_date:
        return None, "", "", "PRICE_PANEL_MISSING"
    d0 = pd.to_datetime(ranking_date)
    s = prices[prices["ticker"].eq(ticker)].sort_values("date")
    if s.empty:
        return None, "", "", "TICKER_PRICE_MISSING"
    start = s[s["date"].le(d0)].tail(1)
    if start.empty:
        return None, "", "", "NO_START_PRICE_ON_OR_BEFORE_RANKING_DATE"
    future = s[s["date"].gt(start["date"].iloc[0])]
    if len(future) < horizon:
        return None, str(start["date"].iloc[0].date()), "", "PENDING_MATURITY"
    end = future.iloc[horizon - 1]
    ret = float(end["adjusted_close"] / start["adjusted_close"].iloc[0] - 1.0)
    return ret, str(start["date"].iloc[0].date()), str(end["date"].date()), "MATURED"


def state_return(holdings: pd.DataFrame, prices: pd.DataFrame, ranking_date: str, horizon: int) -> tuple[float | None, str, int, int]:
    if holdings.empty:
        return None, "STATE_HOLDINGS_UNAVAILABLE", 0, 0
    vals = []
    pending = 0
    valid = 0
    for _, row in holdings.iterrows():
        ret, _, _, status = ticker_forward_return(prices, row["ticker"], ranking_date, horizon)
        if ret is None:
            pending += 1
            continue
        valid += 1
        vals.append(float(row["state_weight"]) * ret)
    if valid == 0:
        return None, "PENDING_MATURITY", valid, pending
    return float(sum(vals)), "MATURED", valid, pending


def build_state_holdings(a1: pd.DataFrame, c2: pd.DataFrame, ai: pd.DataFrame, e: pd.DataFrame, soft: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, dict[str, float], str]]:
    a1_w = top_equal_weight(a1)
    c2_w = top_equal_weight(c2)
    ai_w = top_equal_weight(ai)
    e_col = "ticker_norm" if "ticker_norm" in e.columns else "ticker"
    e_w = top_equal_weight(e, e_col)
    soft_w = soft
    return {
        "A1_CONTROL": combine_components([("A1", a1_w, 1.0)]),
        "C_R2_CHALLENGER": combine_components([("C_R2", c2_w, 1.0)]),
        "AI_BOTTLENECK_THEME": combine_components([("AI_BOTTLENECK", ai_w, 1.0)]),
        "A1_PLUS_C_R2_FORWARD_TRACKING": combine_components([("A1", a1_w, 0.70), ("C_R2", c2_w, 0.30)]),
        "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING": combine_components([("A1", a1_w, 0.60), ("C_R2", c2_w, 0.25), ("AI_BOTTLENECK", ai_w, 0.15)]),
        "A1_PLUS_E_R1_DEFENSIVE_STANDBY": combine_components([("A1", a1_w, 0.70), ("E_R1", e_w, 0.30)]),
        "A1_PLUS_SOFTCAP_WATCH_ONLY": combine_components([("SOFTCAP", soft_w, 1.0)]),
    }


def metadata() -> pd.DataFrame:
    m = read_csv(META)
    if m.empty:
        return pd.DataFrame(columns=["ticker", "sector"])
    m = norm_ticker(m)
    return m[["ticker", "sector"]].drop_duplicates("ticker") if "sector" in m.columns else pd.DataFrame(columns=["ticker", "sector"])


def top_sector_concentration(holdings: pd.DataFrame, meta: pd.DataFrame) -> float:
    if holdings.empty or meta.empty:
        return 0.0
    d = holdings.merge(meta, on="ticker", how="left")
    d["sector"] = d["sector"].fillna("UNKNOWN")
    return float(d.groupby("sector")["state_weight"].sum().max()) if len(d) else 0.0


def ai_subtheme_concentration(ai_conc: pd.DataFrame, bucket: str = "Top20") -> float:
    if ai_conc.empty or "bucket" not in ai_conc.columns or "weight" not in ai_conc.columns:
        return 0.0
    d = ai_conc[ai_conc["bucket"].astype(str).eq(bucket)]
    return float(pd.to_numeric(d["weight"], errors="coerce").max()) if not d.empty else 0.0


def run_stage() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    warnings: list[dict[str, Any]] = []
    switch = read_json(SWITCH_SUMMARY)
    a1 = norm_ticker(read_csv(A1_RANK))
    c2 = norm_ticker(read_csv(C_R2_RANK))
    ai = norm_ticker(read_csv(AI_RANK))
    e = read_csv(E_R1_TOP20)
    soft = softcap_weight()
    prices = price_panel()
    meta = metadata()
    ai_conc = read_csv(AI_CONC)
    ai_warn = read_csv(AI_WARN)
    ai_excl = norm_ticker(read_csv(AI_EXCLUDED))

    ranking_date = latest_date_from_rank(a1, c2, ai) or str(switch.get("latest_price_date_used", ""))
    latest_price = str(prices["date"].max().date()) if not prices.empty else ""
    selected_switch_state = str(switch.get("selected_switch_state", "NO_SWITCH_INSUFFICIENT_EVIDENCE"))
    selected_regime = str(switch.get("selected_regime", "unknown"))
    regime_confidence = float(switch.get("regime_confidence", 0.0) or 0.0)

    holdings_by_state = build_state_holdings(a1, c2, ai, e, soft)
    ledger_rows = []
    attrib_rows = []
    risk_rows = []
    for state in STATES:
        holdings, component_weights, note = holdings_by_state[state]
        valid_holdings = int(holdings["ticker"].nunique()) if not holdings.empty else 0
        for horizon in HORIZONS:
            ret, maturity_status, valid_returns, pending_returns = state_return(holdings, prices, ranking_date, horizon)
            ledger_rows.append({
                "ranking_date": ranking_date,
                "latest_price_date_used": latest_price,
                "tracked_state": state,
                "horizon": f"{horizon}D",
                "maturity_status": maturity_status,
                "forward_return": ret if ret is not None else "",
                "valid_return_count": valid_returns,
                "pending_return_count": pending_returns,
                "valid_holdings_count": valid_holdings,
                "state_notes": note,
                "research_only": True,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "live_trading_allowed": False,
            })
            for component, component_weight in component_weights.items():
                component_holdings = holdings[holdings["state_component"].eq(component)].copy() if not holdings.empty else pd.DataFrame()
                comp_ret, comp_status, _, _ = state_return(component_holdings, prices, ranking_date, horizon)
                attrib_rows.append({
                    "ranking_date": ranking_date,
                    "tracked_state": state,
                    "horizon": f"{horizon}D",
                    "component": component,
                    "component_research_weight": component_weight,
                    "component_forward_return": comp_ret if comp_ret is not None else "",
                    "component_contribution": (component_weight * comp_ret) if comp_ret is not None else "",
                    "maturity_status": comp_status,
                    "research_only": True,
                })
        risk_rows.append({
            "tracked_state": state,
            "valid_holdings_count": valid_holdings,
            "top20_sector_concentration": top_sector_concentration(holdings, meta),
            "top20_subtheme_concentration": ai_subtheme_concentration(ai_conc) if "AI" in state or "AI_BOTTLENECK" in state else "",
            "repeated_loser_count": int(((pd.to_numeric(c2.get("momentum_rs", pd.Series(dtype=float)), errors="coerce").head(20) < 45) | (pd.to_numeric(c2.get("technical_confirm", pd.Series(dtype=float)), errors="coerce").head(20) < 45)).sum()) if "C_R2" in state else "",
            "left_tail_proxy_available": False,
            "data_warning_count": int(ai_warn["warning_type"].astype(str).ne("NONE").sum()) if ("AI" in state and not ai_warn.empty) else 0,
            "research_only": True,
        })

    current_ledger = pd.DataFrame(ledger_rows)
    prior = read_csv(OUT / "switch_state_forward_ledger.csv")
    if not prior.empty:
        current_ledger = pd.concat([prior, current_ledger], ignore_index=True)
    current_ledger = current_ledger.drop_duplicates(["ranking_date", "tracked_state", "horizon"], keep="last")
    current_ledger.to_csv(OUT / "switch_state_forward_ledger.csv", index=False)
    pending = current_ledger[current_ledger["maturity_status"].astype(str).eq("PENDING_MATURITY")].copy()
    matured = current_ledger[current_ledger["maturity_status"].astype(str).eq("MATURED")].copy()
    pending.to_csv(OUT / "switch_state_pending_maturity.csv", index=False)
    matured.to_csv(OUT / "switch_state_matured_results.csv", index=False)

    comparisons = []
    if not matured.empty:
        a1_m = matured[matured["tracked_state"].eq("A1_CONTROL")][["ranking_date", "horizon", "forward_return"]].rename(columns={"forward_return": "a1_forward_return"})
        comp = matured.merge(a1_m, on=["ranking_date", "horizon"], how="left")
        comp["forward_return"] = pd.to_numeric(comp["forward_return"], errors="coerce")
        comp["a1_forward_return"] = pd.to_numeric(comp["a1_forward_return"], errors="coerce")
        comp["excess_return_vs_a1"] = comp["forward_return"] - comp["a1_forward_return"]
        comp["win_vs_a1"] = comp["excess_return_vs_a1"] > 0
        comparisons = comp.to_dict("records")
        comp.to_csv(OUT / "switch_state_vs_a1_comparison.csv", index=False)
    else:
        pd.DataFrame(columns=["ranking_date", "tracked_state", "horizon", "forward_return", "a1_forward_return", "excess_return_vs_a1", "win_vs_a1"]).to_csv(OUT / "switch_state_vs_a1_comparison.csv", index=False)

    regime_snapshot = pd.DataFrame([{
        "ranking_date": ranking_date,
        "latest_price_date_used": latest_price,
        "selected_regime": selected_regime,
        "regime_confidence": regime_confidence,
        "selected_switch_state": selected_switch_state,
        "ai_taxonomy_warning_status": "PRESENT" if not ai_warn.empty and ai_warn["warning_type"].astype(str).str.contains("PIT_LITE", na=False).any() else "ABSENT",
        "concentration_warning_status": "PRESENT" if any(str(w.get("warning_type", "")).startswith("AI_TOP20_THEME_CONCENTRATION") for w in switch.get("warnings", [])) else "ABSENT",
        "research_only": True,
    }])
    regime_snapshot.to_csv(OUT / "switch_state_regime_snapshot.csv", index=False)
    pd.DataFrame(attrib_rows).to_csv(OUT / "switch_state_component_return_attribution.csv", index=False)
    pd.DataFrame(risk_rows).to_csv(OUT / "switch_state_risk_diagnostics.csv", index=False)

    excluded_rows = []
    for ticker in ["HOOD", "WING", "JHX", "AMC"]:
        for horizon in HORIZONS:
            ret, start, end, status = ticker_forward_return(prices, ticker, ranking_date, horizon)
            excluded_rows.append({
                "ticker": ticker,
                "ranking_date": ranking_date,
                "horizon": f"{horizon}D",
                "start_price_date": start,
                "end_price_date": end,
                "excluded_name_forward_return": ret if ret is not None else "",
                "return_available": ret is not None,
                "maturity_status": status,
                "excluded_from_ai_sleeve": True,
                "helped_or_hurt_ai_vs_c_r2": "PENDING_MATURITY" if ret is None else "AVAILABLE_FOR_COMPARISON",
                "research_only": True,
            })
    pd.DataFrame(excluded_rows).to_csv(OUT / "switch_state_excluded_name_impact.csv", index=False)

    if matured.empty:
        warnings.append({"warning_type": "WAIT_MATURITY", "warning": "No 5D/10D/20D rows have matured from the current ranking date."})
    if soft.empty:
        warnings.append({"warning_type": "SOFTCAP_TRACKING_LIMITED", "warning": "Softcap ranking/weights unavailable for current date; watch-only state remains limited."})
    if latest_price and ranking_date and pd.to_datetime(latest_price) <= pd.to_datetime(ranking_date):
        warnings.append({"warning_type": "NO_FORWARD_PRICE_AFTER_RANKING_DATE", "warning": "Latest price panel does not extend beyond ranking date; rows remain pending."})
    warn_df = pd.DataFrame(warnings) if warnings else pd.DataFrame([{"warning_type": "NONE", "warning": ""}])
    warn_df.to_csv(OUT / "switch_state_data_quality_warnings.csv", index=False)

    after = protected_hashes()
    protected_modified = before != after
    final_status = (
        "FAIL_V21_164_SWITCH_FORWARD_LEDGER_SCRIPT_ERROR" if protected_modified
        else "PASS_V21_164_SWITCH_FORWARD_LEDGER_READY" if not matured.empty and not warnings
        else "WARN_V21_164_SWITCH_FORWARD_LEDGER_LIMITED_INPUTS" if len(current_ledger) == 0
        else "PARTIAL_PASS_V21_164_SWITCH_FORWARD_LEDGER_STARTED_WAIT_MATURITY"
    )
    summary = {
        "final_status": final_status,
        "decision": "SWITCH_STATE_FORWARD_TRACKING_WAIT_MATURITY",
        **{**POLICY, "protected_outputs_modified": protected_modified},
        "latest_price_date_used": latest_price,
        "ranking_date": ranking_date,
        "selected_switch_state": selected_switch_state,
        "selected_regime": selected_regime,
        "regime_confidence": regime_confidence,
        "tracked_state_count": len(STATES),
        "pending_maturity_count": int(len(pending)),
        "matured_result_count": int(len(matured)),
        "horizons": [f"{h}D" for h in HORIZONS],
        "a1_primary_control": bool(switch.get("a1_primary_control", True)),
        "c_r2_forward_tracking": bool(switch.get("c_r2_challenger_forward_tracking", False)),
        "ai_bottleneck_forward_tracking": bool(switch.get("ai_bottleneck_theme_forward_tracking", False)),
        "e_r1_standby": not bool(switch.get("e_r1_defensive_forward_tracking", False)),
        "softcap_watch_only": bool(switch.get("softcap_watch_only", False)),
        "tracked_states": STATES,
        "available_vs_a1_comparisons": comparisons,
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    write_json(OUT / f"{STAGE}_summary.json", summary)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={summary['decision']}",
        f"latest_price_date_used={latest_price}",
        f"ranking_date={ranking_date}",
        f"selected_switch_state={selected_switch_state}",
        "tracked_states=" + ", ".join(STATES),
        f"pending_maturity_count={len(pending)}",
        f"matured_result_count={len(matured)}",
        "available_5D_10D_20D_vs_A1=" + ("none" if not comparisons else json.dumps(comparisons[:10])),
        "excluded_name_impact=" + ("pending" if all(not r["return_available"] for r in excluded_rows) else "available"),
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
            "final_status": "FAIL_V21_164_SWITCH_FORWARD_LEDGER_SCRIPT_ERROR",
            "decision": "SWITCH_STATE_FORWARD_TRACKING_WAIT_MATURITY",
            **POLICY,
            "error": str(exc),
            "warning_count": 1,
        }
        write_json(OUT / f"{STAGE}_summary.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not str(summary.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
