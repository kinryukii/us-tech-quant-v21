from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STAGE = "V21.125_ABCD_VS_QQQ_FORWARD_WINRATE_SUMMARY"
OUTDIR = Path("outputs/v21") / STAGE
OUTDIR.mkdir(parents=True, exist_ok=True)

candidate_files = [
    Path("outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH/forward_maturity_by_date_horizon_after_refresh.csv"),
    Path("outputs/v21/V21.119_FORWARD_MATURITY_UPDATE_FOR_ABCD_AND_D_R2C/forward_maturity_by_date_horizon.csv"),
    Path("outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR/early_forward_by_date_horizon.csv"),
]

strategies = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
]


def json_sanitize(value: Any) -> Any:
    """Convert pandas/numpy/path scalar values into strict JSON-safe values."""
    if isinstance(value, dict):
        return {str(json_sanitize(k)): json_sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_sanitize(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) or np.isinf(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def write_manifest(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    safe_payload = json_sanitize(payload)
    path.write_text(json.dumps(safe_payload, indent=2), encoding="utf-8")
    return safe_payload


def find_col(df: pd.DataFrame, names: list[str], required: bool = True) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in cols:
            return cols[name.lower()]
    if required:
        raise SystemExit(f"Missing required column. Tried: {names}. Available: {list(df.columns)}")
    return None


def normalize_topn(value: Any) -> Any:
    text = str(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return int(digits)
    return text


def aggregate(group: pd.DataFrame) -> pd.Series:
    return pd.Series({
        "observations": int(len(group)),
        "win_count": int(group["win_vs_QQQ"].sum()),
        "tie_count": int(group["tie_vs_QQQ"].sum()),
        "loss_count": int(group["loss_vs_QQQ"].sum()),
        "win_rate_vs_QQQ": float(group["win_vs_QQQ"].mean()) if len(group) else None,
        "avg_excess_vs_QQQ": float(group["excess_vs_QQQ_calc"].mean()) if len(group) else None,
        "median_excess_vs_QQQ": float(group["excess_vs_QQQ_calc"].median()) if len(group) else None,
        "best_excess_vs_QQQ": float(group["excess_vs_QQQ_calc"].max()) if len(group) else None,
        "worst_excess_vs_QQQ": float(group["excess_vs_QQQ_calc"].min()) if len(group) else None,
    })


def main() -> dict[str, Any]:
    source_file = next((path for path in candidate_files if path.exists()), None)
    if source_file is None:
        raise SystemExit("No forward maturity source file found. Expected V21.119_R1 or V21.119/V21.117 forward CSV.")

    df = pd.read_csv(source_file)
    if df.empty:
        raise SystemExit(f"Source file is empty: {source_file}")

    strategy_col = find_col(df, ["strategy", "variant", "strategy_variant", "model_variant"])
    ret_col = find_col(df, ["equal_weight_return", "strategy_return", "return"])
    qqq_col = find_col(df, ["benchmark_QQQ_return", "qqq_return"], required=False)
    excess_col = find_col(df, ["excess_vs_QQQ", "excess_qqq"], required=False)
    matured_col = find_col(df, ["matured", "matured_flag"], required=False)
    topn_source_col = find_col(df, ["topN", "top_n", "top_n_name", "selection", "bucket"], required=False)
    horizon_col = find_col(df, ["horizon", "forward_horizon"], required=False)
    date_col = find_col(df, ["ranking_date", "date", "asof_date", "as_of_date"], required=False)
    bucket_col = find_col(df, ["observation_bucket"], required=False)

    x = df.copy()
    x = x[x[strategy_col].astype(str).isin(strategies)].copy()
    if matured_col:
        x = x[x[matured_col].astype(str).str.lower().isin(["true", "1", "yes"])].copy()
    if x.empty:
        raise SystemExit("No matured ABCD/D_R2C rows found.")

    x[ret_col] = pd.to_numeric(x[ret_col], errors="coerce")
    if excess_col:
        x[excess_col] = pd.to_numeric(x[excess_col], errors="coerce")
        x["excess_vs_QQQ_calc"] = x[excess_col]
    elif qqq_col:
        x[qqq_col] = pd.to_numeric(x[qqq_col], errors="coerce")
        x["excess_vs_QQQ_calc"] = x[ret_col] - x[qqq_col]
    else:
        raise SystemExit("Neither excess_vs_QQQ nor benchmark_QQQ_return found.")

    x = x.dropna(subset=["excess_vs_QQQ_calc"]).copy()
    x["topN"] = x[topn_source_col].map(normalize_topn) if topn_source_col else "UNKNOWN"
    if horizon_col is None:
        x["horizon"] = "UNKNOWN"
        horizon_col = "horizon"
    if bucket_col is None:
        x["observation_bucket"] = "ALL_MATURED"
        bucket_col = "observation_bucket"
    x["win_vs_QQQ"] = x["excess_vs_QQQ_calc"] > 0
    x["tie_vs_QQQ"] = x["excess_vs_QQQ_calc"] == 0
    x["loss_vs_QQQ"] = x["excess_vs_QQQ_calc"] < 0

    summary_all = (
        x.groupby([strategy_col, "topN"], dropna=False)
        .apply(aggregate, include_groups=False)
        .reset_index()
        .sort_values(["win_rate_vs_QQQ", "avg_excess_vs_QQQ"], ascending=[False, False])
    )
    summary_by_horizon = (
        x.groupby([strategy_col, "topN", horizon_col], dropna=False)
        .apply(aggregate, include_groups=False)
        .reset_index()
        .sort_values(["topN", horizon_col, "win_rate_vs_QQQ", "avg_excess_vs_QQQ"], ascending=[True, True, False, False])
    )
    summary_by_bucket = (
        x.groupby([strategy_col, "topN", bucket_col], dropna=False)
        .apply(aggregate, include_groups=False)
        .reset_index()
        .sort_values([bucket_col, "topN", "win_rate_vs_QQQ", "avg_excess_vs_QQQ"], ascending=[True, True, False, False])
    )

    detail_cols = [c for c in [date_col, horizon_col, "topN", bucket_col, strategy_col, ret_col, qqq_col, "excess_vs_QQQ_calc", "win_vs_QQQ"] if c and c in x.columns]
    detail = x[detail_cols].copy()

    summary_all_path = OUTDIR / "abcd_vs_qqq_winrate_summary_all_matured.csv"
    summary_horizon_path = OUTDIR / "abcd_vs_qqq_winrate_by_horizon.csv"
    summary_bucket_path = OUTDIR / "abcd_vs_qqq_winrate_by_observation_bucket.csv"
    detail_path = OUTDIR / "abcd_vs_qqq_forward_detail.csv"
    report_path = OUTDIR / "V21.125_abcd_vs_qqq_forward_winrate_report.txt"
    manifest_path = OUTDIR / "V21.125_manifest.json"

    summary_all.to_csv(summary_all_path, index=False, encoding="utf-8-sig")
    summary_by_horizon.to_csv(summary_horizon_path, index=False, encoding="utf-8-sig")
    summary_by_bucket.to_csv(summary_bucket_path, index=False, encoding="utf-8-sig")
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")

    def leader_for_topn(label: int) -> dict[str, Any] | None:
        sub = summary_all[summary_all["topN"].eq(label)]
        if sub.empty:
            return None
        row = sub.iloc[0]
        return {
            "strategy": str(row[strategy_col]),
            "topN": int(row["topN"]),
            "observations": int(row["observations"]),
            "win_rate_vs_QQQ": float(row["win_rate_vs_QQQ"]),
            "avg_excess_vs_QQQ": float(row["avg_excess_vs_QQQ"]),
        }

    def win_rate_for(strategy: str, topn: int) -> float | None:
        sub = summary_all[summary_all[strategy_col].astype(str).eq(strategy) & summary_all["topN"].eq(topn)]
        if sub.empty:
            return None
        return float(sub.iloc[0]["win_rate_vs_QQQ"])

    leader_top20 = leader_for_topn(20)
    leader_top50 = leader_for_topn(50)
    d_r2c_top20_rate = win_rate_for("D_R2C_BC_CONFIRMATION_OVERLAY", 20)

    lines = [
        "V21.125 ABCD vs QQQ Forward Win-Rate Summary",
        "=" * 72,
        "FINAL_STATUS=PASS_V21_125_ABCD_VS_QQQ_WINRATE_SUMMARY_READY",
        "DECISION=ABCD_VS_QQQ_FORWARD_WINRATE_READY_RESEARCH_ONLY",
        f"source_file={source_file.as_posix()}",
        f"generated_at={datetime.now().isoformat(timespec='seconds')}",
        "",
        "Scope",
        "- Nasdaq proxy: QQQ",
        "- Strategies: A1, B, C, D, D_R2C if available",
        "- Research only; no official adoption; no broker action",
        "",
        "Leader",
        f"- Top20 leader: {leader_top20}",
        f"- Top50 leader: {leader_top50}",
        "",
        "All matured summary",
        summary_all.to_string(index=False),
        "",
        "By horizon summary",
        summary_by_horizon.to_string(index=False),
        "",
        "Conclusion",
        f"- Top20 leader vs QQQ: {leader_top20}",
        f"- Top50 leader vs QQQ: {leader_top50}",
        f"- A1 Top20 win rate vs QQQ: {win_rate_for('A1_BASELINE_CONTROL', 20)}",
        f"- B Top20 win rate vs QQQ: {win_rate_for('B_STATIC_MOMENTUM_BLEND', 20)}",
        f"- C Top20 win rate vs QQQ: {win_rate_for('C_DYNAMIC_MOMENTUM_BLEND', 20)}",
        f"- D Top20 win rate vs QQQ: {win_rate_for('D_WEIGHT_OPTIMIZED_R1', 20)}",
        f"- D_R2C Top20 win rate vs QQQ: {d_r2c_top20_rate}",
        "- D_R2C remains tracking-only: true",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "PASS_V21_125_ABCD_VS_QQQ_WINRATE_SUMMARY_READY",
        "DECISION": "ABCD_VS_QQQ_FORWARD_WINRATE_READY_RESEARCH_ONLY",
        "source_file": source_file,
        "strategies_evaluated": strategies,
        "nasdaq_proxy": "QQQ",
        "row_count_matured": len(x),
        "summary_all_path": summary_all_path,
        "summary_horizon_path": summary_horizon_path,
        "summary_bucket_path": summary_bucket_path,
        "detail_path": detail_path,
        "report_path": report_path,
        "leader_top20": leader_top20,
        "leader_top50": leader_top50,
        "A1_Top20_win_rate_vs_QQQ": win_rate_for("A1_BASELINE_CONTROL", 20),
        "B_Top20_win_rate_vs_QQQ": win_rate_for("B_STATIC_MOMENTUM_BLEND", 20),
        "C_Top20_win_rate_vs_QQQ": win_rate_for("C_DYNAMIC_MOMENTUM_BLEND", 20),
        "D_Top20_win_rate_vs_QQQ": win_rate_for("D_WEIGHT_OPTIMIZED_R1", 20),
        "D_R2C_Top20_win_rate_vs_QQQ": d_r2c_top20_rate,
        "D_R2C_remains_tracking_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "model_parameters_changed": False,
        "rankings_recomputed": False,
        "new_strategy_variants_created": False,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    safe_manifest = write_manifest(manifest_path, manifest)

    print(json.dumps(safe_manifest, indent=2))
    print("")
    print("ALL_MATURED_SUMMARY")
    print(summary_all.to_string(index=False))
    print("")
    print("CONCLUSION")
    print(f"Top20 leader vs QQQ: {leader_top20}")
    print(f"Top50 leader vs QQQ: {leader_top50}")
    print(f"A1 Top20 win rate vs QQQ: {win_rate_for('A1_BASELINE_CONTROL', 20)}")
    print(f"B Top20 win rate vs QQQ: {win_rate_for('B_STATIC_MOMENTUM_BLEND', 20)}")
    print(f"C Top20 win rate vs QQQ: {win_rate_for('C_DYNAMIC_MOMENTUM_BLEND', 20)}")
    print(f"D Top20 win rate vs QQQ: {win_rate_for('D_WEIGHT_OPTIMIZED_R1', 20)}")
    print(f"D_R2C Top20 win rate vs QQQ: {d_r2c_top20_rate}")
    print("D_R2C remains tracking-only: true")
    return safe_manifest


if __name__ == "__main__":
    main()
