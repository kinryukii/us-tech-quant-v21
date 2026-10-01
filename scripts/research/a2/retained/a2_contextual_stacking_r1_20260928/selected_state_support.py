"""Read-only selected-versus-unselected state coverage for validation M1."""
from pathlib import Path
import json
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from replay import write, sha


def main():
    source = ROOT/"evaluation_2025/cost_10/M1/action_diagnostics.parquet"
    support_path = ROOT/"panel_artifacts/state_support_2024.json"
    support = json.loads(support_path.read_text(encoding="utf-8"))
    state_fields = ["cash_weight", "current_weight", "available_slots", "realized_vol_20d"]
    flags = [f"out_of_range_{name}" for name in state_fields]
    columns = ["signal_date", "ticker", "action_weight", "action_allowed", "chosen_action", "chosen_weight",
               *state_fields, *flags, "any_state_out_of_range", "any_main_out_of_range"]
    frame = pd.read_parquet(source, columns=columns)
    active = frame.loc[frame.chosen_action & frame.chosen_weight.gt(0)].copy()
    for field in state_fields:
        active[f"train_min_{field}"] = support["min"][field]
        active[f"train_max_{field}"] = support["max"][field]
    active["method"] = "M1"
    active["meta_stage"] = "validation"
    active["status"] = "POST_HOC_SELECTED_TARGET_STATE_SUPPORT_DIAGNOSTIC"
    out = ROOT/"paired_analysis"
    out.mkdir(exist_ok=True)
    active.to_csv(out/"2025_M1_ACTIVE_TARGET_STATE_SUPPORT.csv", index=False)
    feasible = frame.loc[frame.action_allowed]
    stockdays = frame.loc[frame.chosen_action]
    by_date = frame.groupby("signal_date").any_state_out_of_range.mean()
    feasible_by_date = feasible.groupby("signal_date").any_state_out_of_range.mean()
    active_by_date = active.groupby("signal_date").any_state_out_of_range.mean()
    bynd = active.loc[active.ticker.eq("BYND")]
    assert len(active) == 13 and len(bynd) == 9
    assert bynd.any_state_out_of_range.all() and bynd.out_of_range_realized_vol_20d.all()
    assert bynd.chosen_weight.eq(.1).all()
    result = dict(status="POST_HOC_SELECTED_TARGET_STATE_SUPPORT_DIAGNOSTIC",
        year=2025, cost_bps=10, method="M1", stage="validation", no_fit_or_new_replay=True,
        training_state_min=support["min"], training_state_max=support["max"],
        training_cash_99th_percentile=support["quantiles"]["cash_weight"]["0.99"],
        all_candidate_action_rows=len(frame), all_candidate_action_outside_rows=int(frame.any_state_out_of_range.sum()),
        all_candidate_action_outside_row_fraction=float(frame.any_state_out_of_range.mean()),
        all_candidate_action_date_equal_outside_fraction=float(by_date.mean()),
        all_feasible_action_rows=len(feasible), all_feasible_action_outside_rows=int(feasible.any_state_out_of_range.sum()),
        all_feasible_action_outside_row_fraction=float(feasible.any_state_out_of_range.mean()),
        all_feasible_action_date_equal_outside_fraction=float(feasible_by_date.mean()),
        all_stockdays=len(stockdays), all_stockday_outside_rows=int(stockdays.any_state_out_of_range.sum()),
        active_target_stockdays=len(active), active_target_signal_dates=int(active.signal_date.nunique()),
        active_target_outside_rows=int(active.any_state_out_of_range.sum()),
        active_target_outside_row_fraction=float(active.any_state_out_of_range.mean()),
        active_target_date_equal_outside_fraction=float(active_by_date.mean()),
        active_signal_dates_denominator_semantics="Only dates with a positive selected target; cash-only dates excluded from this conditional fraction",
        BYND_active_targets=len(bynd), BYND_target_weights=sorted(bynd.chosen_weight.unique().tolist()),
        BYND_vol_min=float(bynd.realized_vol_20d.min()), BYND_vol_max=float(bynd.realized_vol_20d.max()),
        active_all_cash_state_values=sorted(active.cash_weight.unique().tolist()),
        no_clipping_or_stock_exclusion_or_parameter_change=True,
        interpretation_limit="Range flags are axis-aligned training extrema, not proof of sufficient joint-state density; no removed-stock or clipped-state strategy is evaluated",
        source_sha256={str(source):sha(source),str(support_path):sha(support_path)})
    write(out/"2025_SELECTED_STATE_SUPPORT.json", result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
