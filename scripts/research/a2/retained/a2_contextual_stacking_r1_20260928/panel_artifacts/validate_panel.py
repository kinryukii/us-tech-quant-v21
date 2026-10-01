"""Independent semantic checks of completed causal OOF panel artifacts."""
from pathlib import Path
import json
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import panel
import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits
from train_values import realized_weight as original_realized_weight


def main():
    out = ROOT / "panel_artifacts"
    receipt = json.loads((out / "PANEL_RECEIPT.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    guard = panel.forbid_fitting()
    records = []
    for year in [2024, 2025]:
        k = pd.read_parquet(out / f"panel_keys_{year}.parquet")
        with np.load(out / f"panel_{year}.npz", allow_pickle=False) as saved:
            a = {name: saved[name].copy() for name in saved.files}
        assert a["p"].shape == (len(k) * 5, 12)
        assert a["basis"].shape == (len(k) * 5, 5)
        assert a["z"].shape == (len(k) * 5, 4)
        assert not k.duplicated(["behavior_path", "signal_date", "ticker"]).any()
        assert k.label_end_date.lt(f"{year+1}-01-01").all()
        assert k.execution_date.gt(k.signal_date).all()
        assert k.label_end_date.gt(k.execution_date).all()
        assert np.array_equal(a["row_dates"], np.repeat(k.signal_date.to_numpy(dtype="datetime64[D]"), 5))
        state = k[panel.STATE_ORDER].to_numpy(float)
        assert np.array_equal(a["z"], np.repeat(state, 5, axis=0))
        current = np.repeat(k.current_weight.to_numpy(float), 5)
        action = np.tile(panel.v.ACTIONS, len(k))
        adv = np.repeat(k.avg_dollar_volume_20d.to_numpy(float), 5)
        # Separate vector expression from the generation loop. Sampled scalar
        # comparisons also call the original production label function.
        actual = np.where(action > current, np.minimum(action, current + .01 * adv / 1e6), action)
        forward = np.repeat(k.y_next_open.to_numpy(float), 5)
        vol = np.repeat(k.realized_vol_20d.to_numpy(float), 5)
        fee_and_risk = -.001 * np.abs(actual-current) - 2. * vol**2 * actual**2
        clip = actual * np.clip(forward, -.2, .2) + fee_and_risk
        raw = actual * forward + fee_and_risk
        label_error = float(max(np.max(np.abs(clip-a["target_clip"])), np.max(np.abs(raw-a["target_unclipped"]))))
        assert label_error < 1e-15
        ix = np.unique(np.linspace(0, len(action)-1, 256, dtype=int))
        scalar_error = max(abs(original_realized_weight(float(current[i]), float(action[i]),
                           np.array([adv[i]]))[0] - actual[i]) for i in ix)
        assert scalar_error < 1e-15
        allowed = (np.repeat((k.new_buy_eligible & ~k.buy_restricted).to_numpy(bool), 5) |
                   (action <= current + 1e-10)) & ((a["z"][:,2] > 0) | (action == 0)) & (
                       action <= np.repeat(k.available_weight.to_numpy(float), 5) + 1e-10)
        assert np.array_equal(allowed, a["allowed"])
        rows = pd.DataFrame({"date": a["row_dates"], "path": np.repeat(k.behavior_path.to_numpy(str),5),
                             "weight": a["weights"], "allowed": allowed})
        day_sum = rows.groupby("date").weight.sum()
        path_sum = rows.groupby(["date", "path"]).weight.sum()
        desired = .5 if year == 2025 else 1.
        assert np.allclose(day_sum, 1., rtol=0., atol=1e-15)
        assert np.allclose(path_sum, desired, rtol=0., atol=1e-15)
        assert (rows.loc[~allowed,"weight"] == 0).all()
        assert all(g.loc[g.allowed,"weight"].nunique()==1 for _,g in rows.groupby(["date","path"]))
        selected = np.unique(np.r_[np.linspace(0,len(k)-1,64,dtype=int),
            k.current_weight.nlargest(8).index.to_numpy(), k.age.nlargest(8).index.to_numpy()])
        base = panel.e.BaseBundle(panel.STAGES[year])
        sub = k.iloc[selected]
        with threadpool_limits(limits=2), torch.no_grad():
            r, _ = panel.build_matrix(sub, base)
        action_ix = (selected[:,None]*5 + np.arange(5)[None,:]).ravel()
        prediction_error = float(np.max(np.abs(r["p"] - a["p"][action_ix])))
        assert prediction_error < 2e-5
        assert np.array_equal(r["basis"], a["basis"][action_ix])
        assert base.hashes == receipt["actual_loaded_experts"][str(year)]["hashes"]
        records.append(dict(year=year, stock_dates=len(k), action_rows=len(action),
            exact_label_max_abs_error=label_error, original_scalar_capacity_max_abs_error=float(scalar_error),
            frozen_expert_reinference_stock_dates=len(selected), frozen_expert_reinference_max_abs_error=prediction_error,
            day_weight_max_abs_error=float((day_sum-1.).abs().max()),
            path_weight_max_abs_error=float((path_sum-desired).abs().max()),
            state_identity_exact=True, allowed_mask_exact=True, all_checks_passed=True))
    assert guard["attempts"] == 0
    assert all(panel.sha(p) == h for p,h in receipt["source_sha256"].items())
    result = dict(status="PASS", fit_attempts=0, all_source_hashes_unchanged=True,
                  validation_method="independent label expression, original scalar capacity, persisted-account state identity, date/path weighting, fresh frozen-expert inference", years=records)
    panel.write(out / "PANEL_VALIDATION.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
