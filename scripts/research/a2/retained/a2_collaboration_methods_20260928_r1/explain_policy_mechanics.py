"""Read fixed account ledgers to explain cash formation; no fit or replay."""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd
from portfolio_policy import POLICIES

ROOT = Path(__file__).resolve().parent


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    rows, blend_days, sources = [], [], {}
    for year in [2025, 2026]:
        for name in POLICIES:
            folder = ROOT / f"evaluation_{year}" / name
            contexts_path = folder / "signal_contexts.parquet"
            daily_path = folder / "daily.parquet"
            contexts = pd.read_parquet(contexts_path)
            daily = pd.read_parquet(daily_path)
            sources[str(contexts_path)] = sha(contexts_path)
            sources[str(daily_path)] = sha(daily_path)
            assert len(contexts) == (126 if year == 2025 else 181)
            fields = ["final_available_weight", "active_target_weight", "final_reserved_weight"]
            assert np.isfinite(contexts[fields].to_numpy(float)).all()
            planned_cash = 1 - contexts.final_reserved_weight - contexts.active_target_weight
            unused = contexts.final_available_weight - contexts.active_target_weight
            assert unused.ge(-1e-7).all()
            rows.append({"year": year, "policy": name, "signal_days": len(contexts),
                "mean_signal_active_target_weight": float(contexts.active_target_weight.mean()),
                "mean_signal_retained_old_weight": float(contexts.final_reserved_weight.mean()),
                "mean_signal_unused_available_weight": float(unused.mean()),
                "mean_signal_implied_cash": float(planned_cash.mean()),
                "mean_close_actual_cash_all_account_days": float(daily.cash_weight.mean()),
                "signal_and_realized_cash_have_different_clocks": True})
            if name != "decision_blend":
                continue
            raw_path = folder / "raw_model_outputs.parquet"
            raw = pd.read_parquet(raw_path)
            sources[str(raw_path)] = sha(raw_path)
            context_by_date = contexts.set_index("signal_date")
            for item in raw.itertuples():
                assert item.policy_called
                data = json.loads(item.raw_model_outputs_json)
                names = sorted(data)
                matrix = np.asarray([data[ticker]["base_targets"] for ticker in names], float)
                coeff = np.asarray([data[ticker]["coefficients"] for ticker in names], float)
                assert np.allclose(coeff, coeff[0], rtol=0, atol=1e-12)
                assert np.allclose(coeff[0].sum(), 1)
                before = matrix @ coeff[0]
                after = np.asarray([data[ticker]["mapped_weight"] for ticker in names], float)
                assert (after <= before + 1e-10).all() and (after >= 0).all()
                ctx = context_by_date.loc[item.signal_date]
                assert after.sum() + 1e-8 >= ctx.active_target_weight
                hgb_names = {names[i] for i in np.flatnonzero(matrix[:, 1] > 0)}
                kept_names = {names[i] for i in np.flatnonzero(after > 0)}
                blend_days.append({"year": year, "signal_date": str(item.signal_date.date()),
                    "weighted_member_target_before_truncation": float(before.sum()),
                    "mapped_target_after_policy_truncation": float(after.sum()),
                    "weight_removed_by_truncation_and_downscale": float(before.sum() - after.sum()),
                    "engine_adapted_active_target": float(ctx.active_target_weight),
                    "additional_weight_removed_by_common_account_adapter": float(after.sum() - ctx.active_target_weight),
                    "target_names_equal_hgb_member_in_same_account_context": kept_names == hgb_names,
                    "kept_target_names": len(kept_names), "available_slots": int(ctx.available_slots),
                    "frozen_hgb_coefficient_exceeds_other_two_total": bool(coeff[0, 1] > coeff[0, 0] + coeff[0, 2])})
    pd.DataFrame(rows).to_csv(ROOT / "POLICY_MECHANICS.csv", index=False)
    days = pd.DataFrame(blend_days)
    days.to_csv(ROOT / "DECISION_BLEND_DAYS.csv", index=False)
    summaries = []
    for year, part in days.groupby("year", sort=True):
        summaries.append({"year": int(year), "signal_days": len(part),
            "mean_weight_removed_by_truncation_and_downscale": float(part.weight_removed_by_truncation_and_downscale.mean()),
            "mean_before_truncation_weight": float(part.weighted_member_target_before_truncation.mean()),
            "mean_after_policy_truncation_weight": float(part.mapped_target_after_policy_truncation.mean()),
            "mean_common_account_adapter_reduction": float(part.additional_weight_removed_by_common_account_adapter.mean()),
            "common_adapter_changed_days": int(part.additional_weight_removed_by_common_account_adapter.gt(1e-8).sum()),
            "target_names_equal_hgb_member_in_same_account_context_days": int(part.target_names_equal_hgb_member_in_same_account_context.sum()),
            "hgb_coefficient_dominates_other_two_sum_days": int(part.frozen_hgb_coefficient_exceeds_other_two_total.sum())})
    receipt = {"status": "PASS_READ_ONLY_POLICY_MECHANICS", "fit_calls": 0, "replay_calls": 0,
        "policy_window_rows": len(rows), "decision_blend_summary": summaries,
        "signal_targets_are_not_realized_close_weights": True,
        "cash_difference_is_not_causal_cash_timing_alpha": True,
        "target_set_identity_is_same_context_not_cross_account_path_identity": True,
        "source_sha256": sources}
    (ROOT / "POLICY_MECHANICS_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in receipt.items() if k != "source_sha256"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
