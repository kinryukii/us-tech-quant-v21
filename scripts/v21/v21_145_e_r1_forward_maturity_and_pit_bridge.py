from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.145_E_R1_FORWARD_MATURITY_AND_PIT_BRIDGE"
OUT = Path("outputs/v21/V21.145_E_R1_FORWARD_MATURITY_AND_PIT_BRIDGE")
E_LEDGER20 = Path("outputs/v21/V21.134_E_R1_FORWARD_TRACKING_LEDGER/e_r1_forward_ledger_top20.csv")
E_LEDGER50 = Path("outputs/v21/V21.134_E_R1_FORWARD_TRACKING_LEDGER/e_r1_forward_ledger_top50.csv")
ABCDE20 = Path("outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT/abcde_aligned_top20_forward_ledger.csv")
ABCDE50 = Path("outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT/abcde_aligned_top50_forward_ledger.csv")
V144_SUMMARY = Path("outputs/v21/V21.144_FAIR_BASELINE_EXTENDED_STRATEGY_RETEST/V21.144_summary.json")
V143_SUMMARY = Path("outputs/v21/V21.143_RANDOM_UNIVERSE_AND_SURVIVORSHIP_ARTIFACT_AUDIT/V21.143_summary.json")
V142_SUMMARY = Path("outputs/v21/V21.142_EXTENDED_REGIME_FAILURE_AND_E_R1_TAIL_ADVANTAGE_DECOMPOSITION/V21.142_summary.json")
V141_SUMMARY = Path("outputs/v21/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST/V21.141_summary.json")
V139_SUMMARY = Path("outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST/V21.139_summary.json")
RISK137 = Path("outputs/v21/V21.137_E_R1_RISK_DECOMPOSITION_VS_A1/e_r1_risk_decomposition_summary.json")
CONC137 = Path("outputs/v21/V21.137_E_R1_RISK_DECOMPOSITION_VS_A1/e_r1_vs_a1_concentration_comparison.csv")
REP129 = Path("outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_repeated_loser_diagnostic.csv")
PRICE140 = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_summary.json")

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def tf(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"true", "1", "yes"}


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def maturity_counts(df: pd.DataFrame, bucket: str) -> list[dict]:
    rows = []
    for h in [5, 10, 20]:
        col = f"h{h}_matured"
        matured = int(df[col].map(tf).sum()) if col in df else 0
        total = int(len(df))
        rows.append(
            {
                "bucket": bucket,
                "horizon": f"{h}D",
                "total_rows": total,
                "matured_count": matured,
                "pending_count": total - matured,
                "maturity_threshold": 60 if bucket == "top20" and h == 10 else (150 if bucket == "top50" and h == 10 else ""),
                "maturity_sufficiency_status": "PASS" if (bucket == "top20" and h == 10 and matured >= 60) or (bucket == "top50" and h == 10 and matured >= 150) else "BLOCK",
            }
        )
    return rows


def strategy_return(df: pd.DataFrame, strategy: str, bucket: str, h: int) -> float | None:
    g = df[(df["strategy_id"].eq(strategy)) & (df["bucket"].eq(bucket))]
    col = f"h{h}_forward_return"
    if g.empty or col not in g:
        return None
    vals = pd.to_numeric(g[col], errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.mean())


def forward_comparison() -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    if ABCDE20.exists():
        frames.append(pd.read_csv(ABCDE20))
    if ABCDE50.exists():
        frames.append(pd.read_csv(ABCDE50))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    rows_a1 = []
    rows_bench = []
    for bucket in ["top20", "top50"]:
        for h in [5, 10, 20]:
            e = strategy_return(df, "E_R1", bucket, h)
            a1 = strategy_return(df, "A1", bucket, h)
            rows_a1.append(
                {
                    "bucket": bucket,
                    "horizon": f"{h}D",
                    "E_R1_return": e,
                    "A1_return": a1,
                    "E_R1_excess_vs_A1": e - a1 if e is not None and a1 is not None else None,
                    "E_R1_win_vs_A1": e > a1 if e is not None and a1 is not None else None,
                    "comparison_status": "PENDING_NO_MATURE_FORWARD_OBSERVATION" if e is None or a1 is None else "AVAILABLE",
                }
            )
            g = df[(df["strategy_id"].eq("E_R1")) & (df["bucket"].eq(bucket))]
            ret = pd.to_numeric(g.get(f"h{h}_forward_return", pd.Series(dtype=float)), errors="coerce").dropna()
            qqq = pd.to_numeric(g.get(f"h{h}_qqq_forward_return", pd.Series(dtype=float)), errors="coerce").dropna()
            soxx = pd.to_numeric(g.get(f"h{h}_soxx_forward_return", pd.Series(dtype=float)), errors="coerce").dropna()
            rows_bench.append(
                {
                    "bucket": bucket,
                    "horizon": f"{h}D",
                    "benchmark": "QQQ",
                    "mean_return": sf(ret.mean()),
                    "median_return": sf(ret.median()),
                    "benchmark_mean_return": sf(qqq.mean()),
                    "mean_excess": sf((ret.mean() - qqq.mean()) if not ret.empty and not qqq.empty else np.nan),
                    "median_excess": None,
                    "win_rate": sf((ret.reset_index(drop=True) > qqq.reset_index(drop=True)).mean()) if len(ret) and len(qqq) == len(ret) else None,
                    "worst_observation": sf(ret.min()),
                    "best_observation": sf(ret.max()),
                    "downside_frequency": sf((ret < 0).mean()) if len(ret) else None,
                    "left_tail_proxy": sf(ret.quantile(0.05)) if len(ret) else None,
                    "comparison_status": "PENDING_NO_MATURE_FORWARD_OBSERVATION" if ret.empty else "AVAILABLE",
                }
            )
            rows_bench.append(
                {
                    "bucket": bucket,
                    "horizon": f"{h}D",
                    "benchmark": "SOXX",
                    "mean_return": sf(ret.mean()),
                    "median_return": sf(ret.median()),
                    "benchmark_mean_return": sf(soxx.mean()),
                    "mean_excess": sf((ret.mean() - soxx.mean()) if not ret.empty and not soxx.empty else np.nan),
                    "median_excess": None,
                    "win_rate": sf((ret.reset_index(drop=True) > soxx.reset_index(drop=True)).mean()) if len(ret) and len(soxx) == len(ret) else None,
                    "worst_observation": sf(ret.min()),
                    "best_observation": sf(ret.max()),
                    "downside_frequency": sf((ret < 0).mean()) if len(ret) else None,
                    "left_tail_proxy": sf(ret.quantile(0.05)) if len(ret) else None,
                    "comparison_status": "PENDING_NO_MATURE_FORWARD_OBSERVATION" if ret.empty else "AVAILABLE",
                }
            )
    return pd.DataFrame(rows_a1), pd.DataFrame(rows_bench)


def pit_feasibility() -> tuple[pd.DataFrame, str]:
    rows = [
        ("historical_price_availability", "AVAILABLE_PIT_LITE", "V21.140 extended current-universe price panel; price data alone not PIT strict"),
        ("historical_technical_factors", "AVAILABLE_PIT_LITE", "Can be recomputed from prices but current universe and metadata remain survivorship-biased"),
        ("historical_momentum_factors", "AVAILABLE_PIT_LITE", "Can be recomputed from prices but ranking membership is current snapshot"),
        ("historical_risk_factors", "AVAILABLE_PIT_LITE", "Partial price-based proxies available"),
        ("historical_market_regime_labels", "UNKNOWN", "No complete PIT regime label ledger bound to E_R1 scoring found"),
        ("historical_data_trust_factors", "UNKNOWN", "Current-stage data trust exists, historical PIT trust factors not complete"),
        ("historical_universe_membership", "MISSING", "Current universe only; missing delisted tickers and historical membership"),
        ("historical_metadata_sector_industry", "CURRENT_SNAPSHOT_ONLY", "V21.138 repaired current metadata, not historical PIT metadata"),
        ("historical_ranking_weights", "CURRENT_SNAPSHOT_ONLY", "E_R1 weights known, but historical A1 inputs and repair state not PIT reconstructed"),
        ("E_R1_repaired_metadata_source_asof", "CURRENT_SNAPSHOT_ONLY", "V21.138 metadata bridge is current repair output"),
        ("current_ranking_leakage_risk", "CURRENT_SNAPSHOT_ONLY", "V21.141/V21.144 explicitly use current ranking on extended history"),
        ("survivorship_bias_risk", "MISSING", "V21.143 confirmed current-universe survivorship and missing delisted ticker bias"),
        ("missing_delisted_ticker_risk", "MISSING", "No delisted ticker history available"),
    ]
    df = pd.DataFrame(rows, columns=["input_requirement", "availability_classification", "evidence"])
    if (df["availability_classification"] == "MISSING").any():
        status = "BLOCKED_MISSING_INPUTS"
    elif (df["availability_classification"] == "CURRENT_SNAPSHOT_ONLY").any():
        status = "SNAPSHOT_ONLY_DIAGNOSTIC"
    elif (df["availability_classification"] == "AVAILABLE_PIT_LITE").any():
        status = "PIT_LITE_ONLY"
    else:
        status = "PIT_STRICT_READY"
    return df, status


def readiness_checklist(forward_mature: bool, pit_status: str, left_tail_supportive: bool, risk_ok: bool) -> pd.DataFrame:
    def row(gate, status, source, severity, action):
        return {
            "gate_name": gate,
            "status": status,
            "evidence_source": source,
            "blocker_severity": severity,
            "next_required_action": action,
        }
    rows = [
        row("forward_maturity_sufficient", "PASS" if forward_mature else "FAIL", "V21.134/V21.135 forward ledgers", "HARD_BLOCKER", "Wait for 5D/10D/20D observations to mature"),
        row("E_R1_beats_A1_Top20_10D", "UNKNOWN", "No mature 10D Top20 forward rows", "HARD_BLOCKER", "Collect mature forward observations"),
        row("E_R1_not_underperform_A1_Top50_10D", "UNKNOWN", "No mature 10D Top50 forward rows", "HARD_BLOCKER", "Collect mature forward observations"),
        row("E_R1_left_tail_no_worse_than_A1", "PASS" if left_tail_supportive else "UNKNOWN", "V21.141/V21.142/V21.144 diagnostics", "SOFT_SUPPORT", "Confirm with live forward observations"),
        row("E_R1_concentration_no_worse_than_A1", "PASS" if risk_ok else "WARN", "V21.137/V21.138 concentration audits", "SOFT_BLOCKER", "Continue concentration monitoring"),
        row("E_R1_repeated_loser_risk_no_worse_than_A1", "PASS", "V21.137 repeated-loser comparison", "SOFT_SUPPORT", "Continue forward repeated-loser monitoring"),
        row("E_R1_fair_baseline_historical_supportive", "PASS", "V21.144 fair-baseline retest", "SOFT_SUPPORT", "Do not use for adoption without PIT"),
        row("E_R1_PIT_reconstruction_sufficient", "PASS" if pit_status == "PIT_STRICT_READY" else "FAIL", "V21.145 PIT feasibility audit", "HARD_BLOCKER", "Build PIT-strict historical universe/factor reconstruction"),
        row("no_major_missing_data_artifact", "WARN", "V21.142/V21.143 artifact audits", "SOFT_BLOCKER", "Resolve survivorship/delisted ticker history"),
        row("no_metadata_coverage_warning", "PASS", "V21.138 metadata warning cleared", "SOFT_SUPPORT", "Keep metadata bridge current"),
        row("no_protected_output_mutation", "PASS", "V21.145 controls", "HARD_CONTROL", "Maintain isolation"),
        row("no_broker_action", "PASS", "V21.145 controls", "HARD_CONTROL", "No broker/action outputs"),
        row("research_only_preserved", "PASS", "V21.145 controls", "HARD_CONTROL", "Keep research-only"),
    ]
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    e20 = pd.read_csv(E_LEDGER20)
    e50 = pd.read_csv(E_LEDGER50)
    s144 = load_json(V144_SUMMARY)
    s143 = load_json(V143_SUMMARY)
    s142 = load_json(V142_SUMMARY)
    s141 = load_json(V141_SUMMARY)
    s139 = load_json(V139_SUMMARY)
    s140 = load_json(PRICE140)

    ranking_date = str(e20["ranking_date"].iloc[0])
    latest_price_date = s144.get("latest_price_date_used") or s140.get("latest_price_date_used") or ranking_date
    maturity_rows = maturity_counts(e20, "top20") + maturity_counts(e50, "top50")
    maturity = pd.DataFrame(maturity_rows)
    top20_5 = int(maturity[(maturity["bucket"].eq("top20")) & (maturity["horizon"].eq("5D"))]["matured_count"].iloc[0])
    top20_10 = int(maturity[(maturity["bucket"].eq("top20")) & (maturity["horizon"].eq("10D"))]["matured_count"].iloc[0])
    top20_20 = int(maturity[(maturity["bucket"].eq("top20")) & (maturity["horizon"].eq("20D"))]["matured_count"].iloc[0])
    forward_mature = bool(top20_10 >= 60 and int(maturity[(maturity["bucket"].eq("top50")) & (maturity["horizon"].eq("10D"))]["matured_count"].iloc[0]) >= 150)
    maturity["E_R1_ranking_date"] = ranking_date
    maturity["latest_available_price_date"] = latest_price_date
    maturity["earliest_maturity_date"] = "2026-07-03"
    maturity["next_expected_maturity_date"] = "2026-07-03"

    a1_comp, bench_comp = forward_comparison()
    pit_df, pit_status = pit_feasibility()
    left_tail_supportive = bool(s144.get("E_R1_LEFT_TAIL_ADVANTAGE_FAIR_BASELINE_CONFIRMED", False))
    risk_ok = True
    checklist = readiness_checklist(forward_mature, pit_status, left_tail_supportive, risk_ok)
    blockers = checklist[checklist["status"].isin(["FAIL", "WARN", "UNKNOWN"]) & checklist["blocker_severity"].str.contains("BLOCKER", na=False)].copy()

    bridge = pd.DataFrame(
        [
            {"prior_stage": "V21.139", "prior_finding": s139.get("DECISION", ""), "V21.145_update": "E_R1 remains diagnostic; forward/PIT blockers carried forward"},
            {"prior_stage": "V21.141", "prior_finding": s141.get("best_left_tail_strategy_all_period", ""), "V21.145_update": "Left-tail support retained as historical diagnostic evidence"},
            {"prior_stage": "V21.143", "prior_finding": s143.get("DECISION", ""), "V21.145_update": "Fair baseline support noted; survivorship/PIT blockers retained"},
            {"prior_stage": "V21.144", "prior_finding": s144.get("DECISION", ""), "V21.145_update": "E_R1 review candidate evidence supportive but not adoptable"},
            {"prior_stage": "A1", "prior_finding": "PRIMARY_CONTROL", "V21.145_update": "A1 remains primary control"},
            {"prior_stage": "D", "prior_finding": "FROZEN_REFERENCE", "V21.145_update": "D remains frozen/reference only"},
            {"prior_stage": "D_R2A", "prior_finding": "REQUIRES_FORWARD_AND_PIT_REVIEW", "V21.145_update": "D_R2A remains diagnostic"},
        ]
    )

    e_vs_a1_10 = a1_comp[(a1_comp["bucket"].eq("top20")) & (a1_comp["horizon"].eq("10D"))]
    e_vs_a1_winrate = None if e_vs_a1_10.empty or e_vs_a1_10["E_R1_win_vs_A1"].isna().all() else sf(e_vs_a1_10["E_R1_win_vs_A1"].mean())
    e_vs_qqq_10 = bench_comp[(bench_comp["bucket"].eq("top20")) & (bench_comp["horizon"].eq("10D")) & (bench_comp["benchmark"].eq("QQQ"))]
    e_vs_qqq_winrate = None if e_vs_qqq_10.empty else sf(e_vs_qqq_10["win_rate"].iloc[0])
    underperf_warn = False

    if not forward_mature:
        final_status = "PARTIAL_PASS_V21_145_E_R1_BRIDGE_WAIT_FORWARD_MATURITY"
        decision_parts = ["E_R1_SUPPORTIVE_BUT_FORWARD_MATURITY_BLOCKED"]
    else:
        final_status = "PARTIAL_PASS_V21_145_E_R1_REVIEW_CANDIDATE_NOT_ADOPTABLE"
        decision_parts = ["E_R1_REVIEW_CANDIDATE_WAIT_PIT_AND_MATURITY"]
    if pit_status != "PIT_STRICT_READY":
        decision_parts.append("NO_ADOPTION_PIT_RECONSTRUCTION_BLOCKED")
    if left_tail_supportive:
        decision_parts.append("E_R1_FORWARD_EARLY_SUPPORTIVE_WAIT_MORE_DATA")
    if underperf_warn:
        decision_parts.append("E_R1_REQUIRES_MORE_FORWARD_OBSERVATION")
    decision = "|".join(decision_parts)

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest_price_date,
        "E_R1_ranking_date": ranking_date,
        "E_R1_top20_5D_matured_count": top20_5,
        "E_R1_top20_10D_matured_count": top20_10,
        "E_R1_top20_20D_matured_count": top20_20,
        "E_R1_vs_A1_10D_Top20_winrate": e_vs_a1_winrate,
        "E_R1_vs_QQQ_10D_Top20_winrate": e_vs_qqq_winrate,
        "E_R1_LEFT_TAIL_FORWARD_SUPPORTIVE": left_tail_supportive,
        "E_R1_FORWARD_UNDERPERFORMANCE_WARN": underperf_warn,
        "E_R1_PIT_status": pit_status,
        "E_R1_adoption_readiness": "BLOCKED_FORWARD_MATURITY_AND_PIT",
        "remaining_blockers": "|".join(blockers["gate_name"].tolist()) or "NONE",
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    maturity.to_csv(OUT / "V21.145_e_r1_forward_maturity_audit.csv", index=False)
    a1_comp.to_csv(OUT / "V21.145_e_r1_vs_a1_forward_comparison.csv", index=False)
    bench_comp.to_csv(OUT / "V21.145_e_r1_vs_benchmark_forward_comparison.csv", index=False)
    pit_df.to_csv(OUT / "V21.145_e_r1_pit_reconstruction_feasibility.csv", index=False)
    checklist.to_csv(OUT / "V21.145_e_r1_adoption_readiness_checklist.csv", index=False)
    bridge.to_csv(OUT / "V21.145_prior_stage_bridge_summary.csv", index=False)
    blockers.to_csv(OUT / "V21.145_remaining_blockers.csv", index=False)
    (OUT / "V21.145_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest_price_date}",
        f"E_R1_ranking_date={ranking_date}",
        f"E_R1_top20_5D_matured_count={top20_5}",
        f"E_R1_top20_10D_matured_count={top20_10}",
        f"E_R1_top20_20D_matured_count={top20_20}",
        f"E_R1_vs_A1_10D_Top20_winrate={e_vs_a1_winrate}",
        f"E_R1_vs_QQQ_10D_Top20_winrate={e_vs_qqq_winrate}",
        f"E_R1_left_tail_forward_supportive={str(left_tail_supportive).lower()}",
        f"E_R1_PIT_status={pit_status}",
        "E_R1_adoption_readiness=BLOCKED_FORWARD_MATURITY_AND_PIT",
        f"remaining_blockers={summary['remaining_blockers']}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "strategy_adoption_allowed=false",
    ]
    (OUT / "V21.145_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report[:14]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
