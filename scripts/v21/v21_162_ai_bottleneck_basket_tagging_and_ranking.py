from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING"
OUT = ROOT / "outputs" / "v21" / STAGE
R1 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR"
ABCD = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"
C_R2 = R1 / "c_r2_r1_shadow_ranking_full.csv"
C_R2_SUMMARY = R1 / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR_summary.json"
A1 = ABCD / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_ORIG = ABCD / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv"
META = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_CACHE.csv"

TAXONOMY = [
    "DRAM_HBM_NAND",
    "STORAGE_HDD_SSD",
    "SEMICAP_EQUIPMENT",
    "ADVANCED_PACKAGING_TEST",
    "DATACENTER_POWER",
    "COOLING_THERMAL",
    "ELECTRIFICATION_GRID",
    "AI_INFRA_INDUSTRIAL",
    "ASIA_AI_SUPPLY_CHAIN",
    "NON_AI_BOTTLENECK",
]

WEIGHTS = {
    "c_r2_repaired_score": 0.45,
    "ai_bottleneck_score": 0.30,
    "a1_score": 0.10,
    "c_original_score": 0.05,
    "risk_control": 0.05,
    "data_trust": 0.05,
}

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "ai_bottleneck_adoption_allowed": False,
}

STATIC_THEME: dict[str, tuple[str, str, int, str]] = {
    "MU": ("DRAM_HBM_NAND", "STORAGE_HDD_SSD", 92, "memory/HBM/NAND static taxonomy"),
    "SNDK": ("DRAM_HBM_NAND", "STORAGE_HDD_SSD", 88, "NAND/storage static taxonomy"),
    "WDC": ("STORAGE_HDD_SSD", "DRAM_HBM_NAND", 92, "HDD/SSD AI storage static taxonomy"),
    "STX": ("STORAGE_HDD_SSD", "AI_INFRA_INDUSTRIAL", 88, "HDD AI storage static taxonomy"),
    "AMAT": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 94, "semicap equipment static taxonomy"),
    "LRCX": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 93, "semicap equipment static taxonomy"),
    "KLAC": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 92, "process control semicap taxonomy"),
    "ASML": ("SEMICAP_EQUIPMENT", "ASIA_AI_SUPPLY_CHAIN", 94, "lithography semicap taxonomy"),
    "ACMR": ("SEMICAP_EQUIPMENT", "ASIA_AI_SUPPLY_CHAIN", 86, "wafer cleaning semicap taxonomy"),
    "ICHR": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 84, "semicap subsystem taxonomy"),
    "AEIS": ("SEMICAP_EQUIPMENT", "DATACENTER_POWER", 82, "semicap power subsystem taxonomy"),
    "ENTG": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 83, "materials/filters semicap taxonomy"),
    "MKSI": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 82, "semicap subsystem taxonomy"),
    "VECO": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 80, "semicap equipment taxonomy"),
    "UCTT": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 78, "semicap subsystem taxonomy"),
    "ONTO": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 82, "metrology semicap taxonomy"),
    "ACLS": ("SEMICAP_EQUIPMENT", "ADVANCED_PACKAGING_TEST", 79, "semicap implant taxonomy"),
    "AMKR": ("ADVANCED_PACKAGING_TEST", "ASIA_AI_SUPPLY_CHAIN", 86, "outsourced assembly/test taxonomy"),
    "FORM": ("ADVANCED_PACKAGING_TEST", "SEMICAP_EQUIPMENT", 84, "probe card/test taxonomy"),
    "TER": ("ADVANCED_PACKAGING_TEST", "SEMICAP_EQUIPMENT", 83, "semiconductor test taxonomy"),
    "COHU": ("ADVANCED_PACKAGING_TEST", "SEMICAP_EQUIPMENT", 80, "semiconductor test handler taxonomy"),
    "AEHR": ("ADVANCED_PACKAGING_TEST", "SEMICAP_EQUIPMENT", 77, "semiconductor test taxonomy"),
    "VRT": ("DATACENTER_POWER", "COOLING_THERMAL", 93, "data center power/cooling taxonomy"),
    "ETN": ("DATACENTER_POWER", "ELECTRIFICATION_GRID", 90, "electrical equipment/data center power taxonomy"),
    "POWL": ("DATACENTER_POWER", "ELECTRIFICATION_GRID", 84, "electrical infrastructure taxonomy"),
    "BE": ("DATACENTER_POWER", "AI_INFRA_INDUSTRIAL", 74, "power generation static taxonomy"),
    "CARR": ("COOLING_THERMAL", "AI_INFRA_INDUSTRIAL", 82, "cooling/HVAC taxonomy"),
    "TT": ("COOLING_THERMAL", "AI_INFRA_INDUSTRIAL", 82, "cooling/HVAC taxonomy"),
    "MTZ": ("ELECTRIFICATION_GRID", "AI_INFRA_INDUSTRIAL", 82, "grid construction taxonomy"),
    "PWR": ("ELECTRIFICATION_GRID", "AI_INFRA_INDUSTRIAL", 84, "grid construction taxonomy"),
    "GEV": ("ELECTRIFICATION_GRID", "DATACENTER_POWER", 82, "grid/power equipment taxonomy"),
    "FIX": ("AI_INFRA_INDUSTRIAL", "COOLING_THERMAL", 72, "industrial infrastructure taxonomy"),
    "WWD": ("AI_INFRA_INDUSTRIAL", "DATACENTER_POWER", 70, "industrial controls taxonomy"),
    "TSM": ("ASIA_AI_SUPPLY_CHAIN", "ADVANCED_PACKAGING_TEST", 92, "foundry/CoWoS AI supply chain taxonomy"),
    "TSEM": ("ASIA_AI_SUPPLY_CHAIN", "SEMICAP_EQUIPMENT", 76, "specialty foundry supply-chain taxonomy"),
    "STM": ("ASIA_AI_SUPPLY_CHAIN", "DATACENTER_POWER", 70, "Asia/Europe semiconductor supply-chain taxonomy"),
    "ASX": ("ASIA_AI_SUPPLY_CHAIN", "ADVANCED_PACKAGING_TEST", 80, "Taiwan packaging/test taxonomy"),
    "UMC": ("ASIA_AI_SUPPLY_CHAIN", "SEMICAP_EQUIPMENT", 74, "Taiwan foundry taxonomy"),
    "EWY": ("ASIA_AI_SUPPLY_CHAIN", "DRAM_HBM_NAND", 76, "Korea AI supply-chain ETF proxy taxonomy"),
    "SMH": ("ASIA_AI_SUPPLY_CHAIN", "SEMICAP_EQUIPMENT", 78, "semiconductor ETF proxy taxonomy"),
    "SOXX": ("ASIA_AI_SUPPLY_CHAIN", "SEMICAP_EQUIPMENT", 78, "semiconductor ETF proxy taxonomy"),
}

KEYWORDS = {
    "DRAM_HBM_NAND": ["dram", "hbm", "memory", "nand", "flash"],
    "STORAGE_HDD_SSD": ["hard disk", "hdd", "ssd", "storage", "solid state"],
    "SEMICAP_EQUIPMENT": ["semiconductor equipment", "wafer", "deposition", "etch", "lithography", "metrology", "process control"],
    "ADVANCED_PACKAGING_TEST": ["packaging", "assembly", "test", "probe", "interconnect"],
    "DATACENTER_POWER": ["data center", "power", "ups", "switchgear", "electrical"],
    "COOLING_THERMAL": ["cooling", "thermal", "hvac", "chiller"],
    "ELECTRIFICATION_GRID": ["grid", "transmission", "substation", "electrification", "utility"],
    "AI_INFRA_INDUSTRIAL": ["artificial intelligence", "industrial", "automation", "controls"],
    "ASIA_AI_SUPPLY_CHAIN": ["taiwan", "korea", "japan", "singapore", "asia", "foundry"],
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


def boolish(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def score_from_rank(df: pd.DataFrame) -> pd.Series:
    if "final_score" in df.columns:
        s = pd.to_numeric(df["final_score"], errors="coerce")
        if s.notna().any():
            return s
    rank = pd.to_numeric(df.get("rank"), errors="coerce")
    n = max(int(rank.notna().sum()), 1)
    return (100.0 * (n - rank + 1) / n).clip(0, 100)


def normalize_score(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() == 0:
        return x
    if x.max() <= 1.0:
        return x * 100.0
    return x.clip(0, 100)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    c_r2 = read_csv(C_R2)
    a1 = read_csv(A1)
    c_orig = read_csv(C_ORIG)
    meta = read_csv(META)
    for df in [c_r2, a1, c_orig, meta]:
        if not df.empty and "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    summary = read_json(C_R2_SUMMARY)
    return c_r2, a1, c_orig, meta, summary


def keyword_theme(text: str) -> tuple[str, str, int, str]:
    found: list[tuple[str, int]] = []
    hay = text.lower()
    for theme, words in KEYWORDS.items():
        hits = sum(1 for word in words if word in hay)
        if hits:
            found.append((theme, hits))
    if not found:
        return "NON_AI_BOTTLENECK", "", 0, "no local metadata keyword evidence"
    found.sort(key=lambda x: x[1], reverse=True)
    primary = found[0][0]
    secondary = found[1][0] if len(found) > 1 else ""
    score = min(78, 45 + found[0][1] * 12 + (8 if secondary else 0))
    return primary, secondary, score, "local metadata keyword evidence"


def tag_universe(c_r2: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    m = meta.copy()
    if not m.empty:
        m["ticker"] = m["ticker"].astype(str).str.upper().str.strip()
        keep = [
            "ticker", "provider_name", "sector", "industry", "business_summary", "country",
            "theme_hint", "instrument_type", "exposure_metadata_certification_status",
        ]
        m = m[[c for c in keep if c in m.columns]].drop_duplicates("ticker")
    base = c_r2[["ticker"]].drop_duplicates().merge(m, on="ticker", how="left") if not m.empty else c_r2[["ticker"]].drop_duplicates()
    rows = []
    for _, row in base.iterrows():
        ticker = row["ticker"]
        text = " ".join(str(row.get(c, "")) for c in ["sector", "industry", "business_summary", "theme_hint", "country"])
        if ticker in STATIC_THEME:
            primary, secondary, score, reason = STATIC_THEME[ticker]
            source = "PIT_LITE_STATIC_AND_LOCAL_METADATA_TAXONOMY"
            confidence = 0.86 if score >= 85 else 0.74
            manual = False
        else:
            primary, secondary, score, reason = keyword_theme(text)
            source = "PIT_LITE_LOCAL_METADATA_KEYWORD_TAXONOMY"
            confidence = 0.65 if primary != "NON_AI_BOTTLENECK" else 0.30
            manual = primary == "NON_AI_BOTTLENECK" or confidence < 0.60
        eligible = primary != "NON_AI_BOTTLENECK" and score >= 55
        if not eligible:
            primary = "NON_AI_BOTTLENECK"
            secondary = ""
            score = min(score, 30)
            manual = True
            reason = "weak or unavailable AI bottleneck evidence; momentum/C-R2 membership ignored"
        rows.append({
            "ticker": ticker,
            "company_name": "",
            "ai_bottleneck_eligible": eligible,
            "primary_ai_bottleneck_theme": primary,
            "secondary_ai_bottleneck_theme": secondary,
            "ai_bottleneck_score": float(score),
            "tag_confidence": float(confidence),
            "tag_source": source,
            "manual_review_required": manual,
            "reason": reason,
            "sector": row.get("sector", ""),
            "industry": row.get("industry", ""),
            "metadata_certification": row.get("exposure_metadata_certification_status", ""),
        })
    return pd.DataFrame(rows)


def top_set(df: pd.DataFrame, n: int) -> set[str]:
    if df.empty or "ticker" not in df.columns:
        return set()
    tmp = df.copy()
    tmp["ticker"] = tmp["ticker"].astype(str).str.upper().str.strip()
    tmp["rank"] = pd.to_numeric(tmp.get("rank"), errors="coerce")
    if "rank" in tmp.columns and tmp["rank"].notna().any():
        tmp = tmp.sort_values(["rank", "ticker"])
    return set(tmp.head(n)["ticker"])


def build_ranking(c_r2: pd.DataFrame, a1: pd.DataFrame, c_orig: pd.DataFrame, tags: pd.DataFrame, warnings: list[dict[str, Any]]) -> pd.DataFrame:
    df = c_r2.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["c_r2_repaired_score"] = normalize_score(df.get("c_r2_r1_score", pd.Series(np.nan, index=df.index)))
    df["risk_control"] = normalize_score(df.get("risk_control", pd.Series(np.nan, index=df.index)))
    df["data_trust"] = normalize_score(df.get("data_trust", pd.Series(np.nan, index=df.index)))
    df = df.merge(tags[["ticker", "ai_bottleneck_eligible", "primary_ai_bottleneck_theme", "secondary_ai_bottleneck_theme", "ai_bottleneck_score", "tag_confidence", "manual_review_required", "tag_source", "reason"]], on="ticker", how="left")

    a = a1[["ticker"]].copy() if not a1.empty else pd.DataFrame(columns=["ticker"])
    if not a.empty:
        a["a1_score"] = normalize_score(score_from_rank(a1))
        df = df.merge(a[["ticker", "a1_score"]], on="ticker", how="left")
    else:
        df["a1_score"] = np.nan
        warnings.append({"ticker": "ALL", "warning_type": "A1_SCORE_UNAVAILABLE", "warning": "A1 source unavailable; weights renormalized"})
    c = c_orig[["ticker"]].copy() if not c_orig.empty else pd.DataFrame(columns=["ticker"])
    if not c.empty:
        c["c_original_score"] = normalize_score(score_from_rank(c_orig))
        df = df.merge(c[["ticker", "c_original_score"]], on="ticker", how="left")
    else:
        df["c_original_score"] = np.nan
        warnings.append({"ticker": "ALL", "warning_type": "C_ORIGINAL_SCORE_UNAVAILABLE", "warning": "C original source unavailable; weights renormalized"})

    component_cols = list(WEIGHTS)
    available_weights = {}
    for col, weight in WEIGHTS.items():
        if col in df.columns and pd.to_numeric(df[col], errors="coerce").notna().any():
            available_weights[col] = weight
        else:
            warnings.append({"ticker": "ALL", "warning_type": f"{col.upper()}_UNAVAILABLE", "warning": f"{col} unavailable; weights renormalized"})
    weight_sum = sum(available_weights.values()) or 1.0
    df["raw_ai_bottleneck_shadow_score"] = 0.0
    for col, weight in available_weights.items():
        df["raw_ai_bottleneck_shadow_score"] += pd.to_numeric(df[col], errors="coerce").fillna(50.0) * (weight / weight_sum)
    df.loc[~df["ai_bottleneck_eligible"].fillna(False).astype(bool), "raw_ai_bottleneck_shadow_score"] *= 0.35
    df.loc[df["manual_review_required"].fillna(True).astype(bool), "raw_ai_bottleneck_shadow_score"] *= 0.90
    df.loc[df["tag_confidence"].fillna(0) < 0.60, "raw_ai_bottleneck_shadow_score"] *= 0.90
    prelim = df.sort_values(["raw_ai_bottleneck_shadow_score", "ticker"], ascending=[False, True]).copy()
    theme_counts = prelim.head(50)["primary_ai_bottleneck_theme"].value_counts().to_dict()
    df["theme_concentration_penalty"] = df["primary_ai_bottleneck_theme"].map(lambda x: max(0, theme_counts.get(x, 0) - 12) * 0.015)
    df["ai_bottleneck_shadow_score"] = df["raw_ai_bottleneck_shadow_score"] * (1.0 - df["theme_concentration_penalty"].clip(0, 0.20))
    df = df.sort_values(["ai_bottleneck_shadow_score", "ticker"], ascending=[False, True]).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    df["is_top20"] = df["rank"].le(20)
    df["is_top50"] = df["rank"].le(50)
    df["weight_components_used"] = "|".join(available_weights)
    df["weight_sum_before_renormalization"] = weight_sum
    return df


def concentration(rank: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for bucket, frame in [("Top20", rank.head(20)), ("Top50", rank.head(50))]:
        counts = frame["primary_ai_bottleneck_theme"].value_counts()
        for theme in TAXONOMY:
            count = int(counts.get(theme, 0))
            rows.append({
                "bucket": bucket,
                "primary_ai_bottleneck_theme": theme,
                "count": count,
                "weight": float(count / len(frame)) if len(frame) else 0.0,
            })
    return pd.DataFrame(rows)


def single_name(rank: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for bucket, frame in [("Top20", rank.head(20)), ("Top50", rank.head(50))]:
        total = frame["ai_bottleneck_shadow_score"].sum()
        for _, row in frame.iterrows():
            rows.append({
                "bucket": bucket,
                "ticker": row["ticker"],
                "rank": row["rank"],
                "ai_bottleneck_shadow_score": row["ai_bottleneck_shadow_score"],
                "score_contribution_weight": float(row["ai_bottleneck_shadow_score"] / total) if total else 0.0,
                "primary_ai_bottleneck_theme": row["primary_ai_bottleneck_theme"],
            })
    return pd.DataFrame(rows)


def overlap_rows(rank: pd.DataFrame, a1: pd.DataFrame, c_r2: pd.DataFrame, c_orig: pd.DataFrame) -> pd.DataFrame:
    rows = []
    refs = {"A1": a1, "C_R2_REPAIRED": c_r2, "C_ORIGINAL": c_orig}
    for label, ref in refs.items():
        for n in [20, 50]:
            ai = set(rank.head(n)["ticker"])
            other = top_set(ref, n)
            rows.append({
                "comparison": f"AI_BOTTLENECK_vs_{label}",
                "bucket": f"Top{n}",
                "overlap_count": len(ai & other),
                "entrants": ",".join(sorted(ai - other)),
                "exits": ",".join(sorted(other - ai)),
            })
    return pd.DataFrame(rows)


def risk_stats(rank: pd.DataFrame, tags: pd.DataFrame, conc: pd.DataFrame, single: pd.DataFrame) -> dict[str, Any]:
    top20 = rank.head(20)
    top50 = rank.head(50)
    repeated = int(((pd.to_numeric(top50.get("momentum_rs"), errors="coerce") < 45) | (pd.to_numeric(top50.get("technical_confirm"), errors="coerce") < 45)).sum())
    return {
        "max_single_theme_weight_top20": float(conc[conc["bucket"].eq("Top20")]["weight"].max()),
        "max_single_theme_weight_top50": float(conc[conc["bucket"].eq("Top50")]["weight"].max()),
        "max_single_name_score_contribution_top20": float(single[single["bucket"].eq("Top20")]["score_contribution_weight"].max()),
        "max_single_name_score_contribution_top50": float(single[single["bucket"].eq("Top50")]["score_contribution_weight"].max()),
        "repeated_loser_count_top50": repeated,
        "left_tail_proxy_available": "left_tail_proxy" in rank.columns and pd.to_numeric(rank.get("left_tail_proxy"), errors="coerce").notna().any(),
        "data_warning_ticker_count_top50": int(top50.get("proxy_repair_status", pd.Series("", index=top50.index)).astype(str).ne("REPAIRED_OR_CONFIRMED_FROM_CONTROLLED_FUNDAMENTAL_SOURCE").sum()),
        "manual_review_count": int(tags["manual_review_required"].astype(bool).sum()),
        "non_ai_bottleneck_count": int(tags["primary_ai_bottleneck_theme"].eq("NON_AI_BOTTLENECK").sum()),
        "low_confidence_tag_count": int(pd.to_numeric(tags["tag_confidence"], errors="coerce").lt(0.60).sum()),
    }


def run_stage() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    warnings: list[dict[str, Any]] = []
    c_r2, a1, c_orig, meta, r1_summary = load_inputs()
    if c_r2.empty:
        summary = {
            "final_status": "FAIL_V21_162_AI_BOTTLENECK_SCRIPT_ERROR",
            "decision": "AI_BOTTLENECK_FORWARD_TRACKING_ONLY",
            **POLICY,
            "warning_count": 1,
            "error": "missing C-R2 repaired ranking",
        }
        write_json(OUT / f"{STAGE}_summary.json", summary)
        return summary

    tags = tag_universe(c_r2, meta)
    tags.to_csv(OUT / "ai_bottleneck_universe_tags.csv", index=False)
    rank = build_ranking(c_r2, a1, c_orig, tags, warnings)
    full_cols = [
        "rank", "ticker", "ai_bottleneck_shadow_score", "raw_ai_bottleneck_shadow_score",
        "ai_bottleneck_eligible", "primary_ai_bottleneck_theme", "secondary_ai_bottleneck_theme",
        "ai_bottleneck_score", "tag_confidence", "tag_source", "manual_review_required",
        "c_r2_repaired_score", "a1_score", "c_original_score", "risk_control", "data_trust",
        "theme_concentration_penalty", "is_top20", "is_top50", "reason",
        "latest_price_date_used", "selected_regime", "regime_confidence", "proxy_repair_status",
    ]
    full_cols = [c for c in full_cols if c in rank.columns]
    rank[full_cols].to_csv(OUT / "ai_bottleneck_shadow_ranking_full.csv", index=False)
    rank.head(50)[full_cols].to_csv(OUT / "ai_bottleneck_shadow_ranking_top50.csv", index=False)
    rank.head(20)[full_cols].to_csv(OUT / "ai_bottleneck_top20.csv", index=False)
    conc = concentration(rank)
    conc.to_csv(OUT / "ai_bottleneck_subtheme_concentration.csv", index=False)
    single = single_name(rank)
    single.to_csv(OUT / "ai_bottleneck_single_name_concentration.csv", index=False)
    overlaps = overlap_rows(rank, a1, c_r2, c_orig)
    overlaps.to_csv(OUT / "ai_bottleneck_vs_a1_c_r2_c_overlap.csv", index=False)
    c_r2_top20 = set(c_r2.sort_values("rank").head(20)["ticker"])
    non_eligible = tags[tags["ticker"].isin(c_r2_top20) & ~tags["ai_bottleneck_eligible"].astype(bool)].copy()
    non_eligible.to_csv(OUT / "ai_bottleneck_non_eligible_c_r2_top20.csv", index=False)
    if meta.empty:
        warnings.append({"ticker": "ALL", "warning_type": "METADATA_UNAVAILABLE", "warning": "metadata source unavailable; static taxonomy only"})
    warnings.append({"ticker": "ALL", "warning_type": "PIT_LITE_TAXONOMY", "warning": "static/local metadata taxonomy only; no full PIT validity claimed"})
    if len(non_eligible):
        warnings.append({"ticker": "ALL", "warning_type": "C_R2_TOP20_NON_ELIGIBLE_PRESENT", "warning": f"{len(non_eligible)} C-R2 Top20 names are not AI bottleneck eligible"})
    warn_df = pd.DataFrame(warnings)
    warn_df.to_csv(OUT / "ai_bottleneck_data_quality_warnings.csv", index=False)
    risk = risk_stats(rank, tags, conc, single)

    after = protected_hashes()
    protected_modified = before != after
    final_status = (
        "FAIL_V21_162_AI_BOTTLENECK_SCRIPT_ERROR" if protected_modified
        else "WARN_V21_162_AI_BOTTLENECK_TAXONOMY_LIMITED" if any(w["warning_type"] == "PIT_LITE_TAXONOMY" for w in warnings)
        else "PARTIAL_PASS_V21_162_AI_BOTTLENECK_READY_WITH_WARNINGS" if warnings
        else "PASS_V21_162_AI_BOTTLENECK_TAGGING_READY"
    )
    def ov(label: str, bucket: str) -> int:
        row = overlaps[(overlaps["comparison"].eq(label)) & (overlaps["bucket"].eq(bucket))]
        return int(row["overlap_count"].iloc[0]) if not row.empty else 0

    latest = str(r1_summary.get("latest_price_date_used", rank.get("latest_price_date_used", pd.Series([""])).iloc[0] if len(rank) else ""))
    summary = {
        "final_status": final_status,
        "decision": "AI_BOTTLENECK_FORWARD_TRACKING_ONLY",
        **{**POLICY, "protected_outputs_modified": protected_modified},
        "latest_price_date_used": latest,
        "taxonomy": TAXONOMY,
        "taxonomy_source": "PIT_LITE_STATIC_AND_LOCAL_METADATA_TAXONOMY",
        "ranking_row_count": int(len(rank)),
        "top50_row_count": int(min(50, len(rank))),
        "top20_row_count": int(min(20, len(rank))),
        "ai_bottleneck_top20": rank.head(20)["ticker"].tolist(),
        "overlap_ai_top20_vs_a1_top20": ov("AI_BOTTLENECK_vs_A1", "Top20"),
        "overlap_ai_top50_vs_a1_top50": ov("AI_BOTTLENECK_vs_A1", "Top50"),
        "overlap_ai_top20_vs_c_r2_repaired_top20": ov("AI_BOTTLENECK_vs_C_R2_REPAIRED", "Top20"),
        "overlap_ai_top50_vs_c_r2_repaired_top50": ov("AI_BOTTLENECK_vs_C_R2_REPAIRED", "Top50"),
        "overlap_ai_top20_vs_c_original_top20": ov("AI_BOTTLENECK_vs_C_ORIGINAL", "Top20"),
        "overlap_ai_top50_vs_c_original_top50": ov("AI_BOTTLENECK_vs_C_ORIGINAL", "Top50"),
        "c_r2_top20_non_eligible": non_eligible["ticker"].tolist(),
        **risk,
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    write_json(OUT / f"{STAGE}_summary.json", summary)
    top20_conc = conc[conc["bucket"].eq("Top20") & conc["count"].gt(0)][["primary_ai_bottleneck_theme", "count", "weight"]].to_dict("records")
    top50_conc = conc[conc["bucket"].eq("Top50") & conc["count"].gt(0)][["primary_ai_bottleneck_theme", "count", "weight"]].to_dict("records")
    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"decision={summary['decision']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"latest_price_date_used={latest}",
        "AI_BOTTLENECK_TOP20=" + ", ".join(summary["ai_bottleneck_top20"]),
        f"Top20_subtheme_concentration={top20_conc}",
        f"Top50_subtheme_concentration={top50_conc}",
        f"overlap_vs_A1_top20={summary['overlap_ai_top20_vs_a1_top20']}",
        f"overlap_vs_A1_top50={summary['overlap_ai_top50_vs_a1_top50']}",
        f"overlap_vs_C_R2_repaired_top20={summary['overlap_ai_top20_vs_c_r2_repaired_top20']}",
        f"overlap_vs_C_R2_repaired_top50={summary['overlap_ai_top50_vs_c_r2_repaired_top50']}",
        f"overlap_vs_C_original_top20={summary['overlap_ai_top20_vs_c_original_top20']}",
        f"overlap_vs_C_original_top50={summary['overlap_ai_top50_vs_c_original_top50']}",
        "C_R2_TOP20_NON_ELIGIBLE=" + ", ".join(summary["c_r2_top20_non_eligible"]),
        f"warnings={summary['warning_count']}",
    ]
    (OUT / f"{STAGE}_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    try:
        summary = run_stage()
    except Exception as exc:  # pragma: no cover
        OUT.mkdir(parents=True, exist_ok=True)
        summary = {
            "final_status": "FAIL_V21_162_AI_BOTTLENECK_SCRIPT_ERROR",
            "decision": "AI_BOTTLENECK_FORWARD_TRACKING_ONLY",
            **POLICY,
            "error": str(exc),
            "warning_count": 1,
        }
        write_json(OUT / f"{STAGE}_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if not str(summary.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
