from __future__ import annotations

from pathlib import Path

import pandas as pd


STAGE = "V21.153_R1_ALL_STRATEGY_SOFTCAP_DELTA_SUMMARY"
SRC = Path("outputs/v21/V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST")
OUT = Path("outputs/v21/V21.153_R1_ALL_STRATEGY_SOFTCAP_DELTA_SUMMARY")
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "E_R1_REPAIRED",
]


def interp(ret: bool, dd: bool, p5: bool) -> str:
    if ret and dd and p5:
        return "IMPROVED_RETURN_DRAWDOWN_AND_LEFT_TAIL"
    if ret and (dd or p5):
        return "RETURN_IMPROVED_WITH_SOME_DEFENSIVE_SUPPORT"
    if ret:
        return "RETURN_IMPROVED_DEFENSE_MIXED"
    if dd and p5:
        return "DEFENSIVE_ONLY_RETURN_LAG"
    if dd or p5:
        return "MIXED_DEFENSIVE_SIGNAL"
    return "NO_SOFTCAP_IMPROVEMENT"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    comp = pd.read_csv(SRC / "realized_window_strategy_comparison.csv")
    rows = []
    for strategy in STRATEGIES:
        base = comp[(comp["strategy_id"].eq(strategy)) & (comp["variant"].eq("EXEC_BASELINE")) & (comp["bucket"].eq("Top20"))]
        soft = comp[(comp["strategy_id"].eq(strategy)) & (comp["variant"].eq("OVERHEAT_SOFT_CAP_R1")) & (comp["bucket"].eq("Top20"))]
        if base.empty or soft.empty:
            continue
        b = base.iloc[0]
        s = soft.iloc[0]
        return_delta = s["cumulative_return_net"] - b["cumulative_return_net"]
        excess_delta = s["excess_return_vs_QQQ"] - b["excess_return_vs_QQQ"]
        drawdown_delta = s["max_drawdown_proxy"] - b["max_drawdown_proxy"]
        p5_delta = s["p5_daily_return"] - b["p5_daily_return"]
        improved_return = return_delta > 0
        improved_drawdown = drawdown_delta >= 0
        improved_left_tail = p5_delta >= 0
        rows.append(
            {
                "strategy": strategy,
                "baseline_return": b["cumulative_return_net"],
                "soft_cap_return": s["cumulative_return_net"],
                "return_delta": return_delta,
                "baseline_excess_vs_QQQ": b["excess_return_vs_QQQ"],
                "soft_cap_excess_vs_QQQ": s["excess_return_vs_QQQ"],
                "excess_delta_vs_QQQ": excess_delta,
                "baseline_max_drawdown": b["max_drawdown_proxy"],
                "soft_cap_max_drawdown": s["max_drawdown_proxy"],
                "drawdown_delta": drawdown_delta,
                "baseline_p5": b["p5_daily_return"],
                "soft_cap_p5": s["p5_daily_return"],
                "p5_delta": p5_delta,
                "improved_return_true_false": improved_return,
                "improved_drawdown_true_false": improved_drawdown,
                "improved_left_tail_true_false": improved_left_tail,
                "overall_interpretation": interp(improved_return, improved_drawdown, improved_left_tail),
                "diagnostic_only": strategy == "E_R1_REPAIRED",
            }
        )
    out = pd.DataFrame(rows)
    all_improved = bool(out["improved_return_true_false"].all() and out["improved_drawdown_true_false"].all() and out["improved_left_tail_true_false"].all())
    b_row = out[out["strategy"].eq("B_STATIC_MOMENTUM_BLEND")].iloc[0]
    b_helped = bool(b_row["improved_return_true_false"] or b_row["improved_drawdown_true_false"] or b_row["improved_left_tail_true_false"])
    defensive_any = bool((out["improved_drawdown_true_false"] | out["improved_left_tail_true_false"]).any())
    if all_improved:
        final_label = "PASS_SOFTCAP_IMPROVED_ALL_STRATEGIES"
    elif b_helped and not all_improved:
        final_label = "PARTIAL_PASS_SOFTCAP_IMPROVED_B_NOT_ALL"
    elif defensive_any:
        final_label = "PARTIAL_PASS_SOFTCAP_DEFENSIVE_MIXED"
    else:
        final_label = "FAIL_SOFTCAP_NOT_BROADLY_HELPFUL"
    out.to_csv(OUT / "all_strategy_softcap_delta_summary.csv", index=False)
    report = [
        STAGE,
        f"FINAL_LABEL={final_label}",
        "source_stage=V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST",
        f"strategies_compared={'|'.join(out['strategy'])}",
        f"B_return_delta={b_row['return_delta']}",
        f"B_drawdown_delta={b_row['drawdown_delta']}",
        f"B_p5_delta={b_row['p5_delta']}",
        "E_R1_diagnostic_only=true",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"output directory={str(OUT).replace(chr(92), '/')}",
    ]
    (OUT / "compact_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
