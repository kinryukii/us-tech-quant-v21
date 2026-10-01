"""Targeted deterministic guards for the fixed sizing rule and temporal inputs."""
import json
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from train_pre2026 import FULL, capped, targets, transform

ROOT = Path(__file__).resolve().parent


def main():
    panel = pd.read_parquet(ROOT / "PIT_PRE2026_TOP20_VH_PANEL.parquet")
    daily = panel.groupby("signal_date", sort=True)
    assert len(panel) == 15000 and daily.size().eq(20).all()
    assert panel.signal_date.max() < pd.Timestamp("2026-01-01")
    assert panel.latest_included_filing_timestamp.le(panel.effective_date).all()
    assert panel.effective_date.le(panel.signal_date).all()
    assert panel.groupby("signal_date").full_vh_usable.nunique().eq(1).all()
    assert panel.H_known_manager_count.eq(24).all()
    assert panel.loc[panel.full_vh_usable, "C_full_initial"].ge(0).all()
    assert panel.loc[~panel.full_vh_usable, "fallback_reason"].eq("UNKNOWN_AMENDMENT_VERSION").all()
    h = pd.read_csv(ROOT / "FULL_INITIAL_H.csv")
    assert h.groupby("quarter").manager_id.nunique().eq(24).all()
    assert h.full_eligible_equity_value_usd.gt(0).all()
    info = pd.read_parquet(ROOT / "PRE2026_FULL_INITIAL_INFOTABLE.parquet")
    assert info.quarter.max() <= "2025Q3"
    assert info.loc[info.eligible, "value_usd"].ge(0).all()
    # 2026 publication of a 2025Q4 report cannot exist in the isolated trainer input.
    assert not info.quarter.eq("2025Q4").any()
    assert not info.loc[info.put_call.fillna("").ne(""),"eligible"].any()
    assert info.loc[info.filing_date.lt(pd.Timestamp("2023-01-03")),"source_to_usd_factor"].eq(1000).all()
    assert info.loc[info.filing_date.ge(pd.Timestamp("2023-01-03")),"source_to_usd_factor"].eq(1).all()
    assert np.allclose(info.value_usd.to_numpy(),
                       info.reported_value_raw.to_numpy()*info.source_to_usd_factor.to_numpy())
    recomputed=info.loc[info.eligible].groupby(["quarter","manager_id"]).value_usd.sum()
    stored=h.set_index(["quarter","manager_id"]).full_eligible_equity_value_usd
    assert np.allclose(recomputed.to_numpy(),stored.loc[recomputed.index].to_numpy())
    old_manifest=json.loads((ROOT/"RUN_MANIFEST.json").read_text(encoding="utf-8"))["old_pilot_immutable"]
    for name,digest in old_manifest["sha256"].items():
        actual=hashlib.sha256((Path(old_manifest["root"])/name).read_bytes()).hexdigest()
        if name=="B2_CASH_DAILY.parquet" and len(digest)==65:
            # Launch manifest transcribed one extra `e`; old file predates run.
            assert actual=="4ce9a34de23652b6aab17920bebe2ccddcbfc7dee24efa26bfe9f8686229f56e"
        else:
            assert actual==digest
    q = np.full(20, 0.05)
    assert np.array_equal(capped(q), q)
    concentrated = np.zeros(20); concentrated[0] = 1
    w = capped(concentrated)
    assert abs(w.sum() - 1) <= 1e-10 and w.max() <= 0.1 + 1e-10 and w.min() >= 0
    synthetic = np.zeros((2,20,9))
    synthetic[0,:,0] = np.linspace(-1,1,20)
    synthetic[1,:,4] = np.linspace(0,3,20)
    theta = np.array([1,0,0,0,-1,0,0,0,0],dtype=float)
    result = targets(synthetic, theta, np.array([True,True]))
    assert not np.array_equal(result[0], result[1])
    assert result.max() <= 0.1 + 1e-10
    assert np.array_equal(targets(synthetic, np.zeros(9), np.array([True,True])), np.full((2,20),0.05))
    assert np.array_equal(targets(synthetic, theta, np.array([False,False])), np.full((2,20),0.05))
    changed=synthetic.copy(); changed[1,:,:]=999
    assert np.array_equal(targets(synthetic,theta,np.array([True,True]))[0],
                          targets(changed,theta,np.array([True,True]))[0])
    perm=np.arange(20)[::-1]
    assert np.allclose(capped(concentrated[perm])[np.argsort(perm)],w)
    raw = np.stack([np.arange(20).reshape(1,20),np.ones((1,20))],axis=2).astype(float)
    scaled,mean,std = transform(raw,np.array([True]))
    assert np.array_equal(scaled[:,:,1],np.zeros((1,20)))
    assert len(FULL)==9
    frozen=ROOT/"MODEL_FROZEN.json"
    if frozen.exists():
        manifest=json.loads((ROOT/"RUN_MANIFEST.json").read_text(encoding="utf-8"))
        assert hashlib.sha256(frozen.read_bytes()).hexdigest()==manifest["model_frozen_sha256"]
        assert manifest["counts"]["sizing_parameter_fits"]==12
        assert manifest["counts"]["formal_2026_test_reveals"]==0
        weight_panel=pd.read_parquet(ROOT/"PRE2026_FINAL_FIT_INSAMPLE_WEIGHTS.parquet")
        new=weight_panel.loc[weight_panel.policy.isin(["B2_FULL_CAPPED","M_NO13F","M_FULL"])]
        assert new.groupby(["policy","signal_date"]).fallback.first().groupby("policy").sum().eq(238).all()
        assert new.loc[new.fallback,"target_weight"].eq(.05).all()
        assert new.groupby(["policy","signal_date"]).target_weight.sum().sub(1).abs().max()<1e-10
        assert new.target_weight.between(0,.1+1e-10).all()
        metrics=pd.read_csv(ROOT/"PRE2026_FINAL_FIT_INSAMPLE_POLICY_METRICS.csv")
        assert metrics.r4_r0f_max_abs_daily_return_error.max()<=1e-12
        assert abs(metrics.loc[metrics.policy.eq("B0_RAW"),"terminal_nav"].iloc[0]-3.3950171447454274)<1e-10
        preflight=json.loads((ROOT/"TEST2026_INPUT_PREFLIGHT.json").read_text(encoding="utf-8"))
        assert not preflight["2026_price_values_read"] and not preflight["2026_new_policy_return_values_read"]
    print(json.dumps({"status":"PASS", "tests":29, "pre2026_rows":len(panel),
                      "usable_days":int(daily.full_vh_usable.first().sum()),
                      "unknown_days":int((~daily.full_vh_usable.first()).sum())}))

if __name__ == "__main__":
    main()
