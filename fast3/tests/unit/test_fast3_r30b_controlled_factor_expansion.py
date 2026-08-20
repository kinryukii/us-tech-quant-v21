from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2]/"scripts"/"run"/"fast3_r30b_controlled_factor_expansion.py"
SPEC = importlib.util.spec_from_file_location("r30b",SCRIPT); R=importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def bars(n=300, shift_seconds=0):
    t=pd.date_range("2020-01-01",periods=n,freq="min",tz="UTC")+pd.Timedelta(seconds=shift_seconds)
    c=pd.Series(100+np.linspace(0,3,n)+np.sin(np.arange(n)/7),dtype=float)
    return pd.DataFrame({"timestamp_utc":t,"open":c,"high":c+.2,"low":c-.2,"close":c,"volume":1000})


def test_rsi_kdj_macd_and_rolling_features_are_pit_causal():
    original=bars(); changed=original.copy(); changed.loc[250:,"close"]+=100; changed.loc[250:,"high"]+=100; changed.loc[250:,"low"]+=100
    a=R.single_symbol_factors(original); b=R.single_symbol_factors(changed)
    for name in ("RSI_14","KDJ_J_9_3","MACD_HIST_NORM_12_26_9","EMA20_SLOPE_5","PRICE_VS_MA20","REALIZED_VOL_5","ATR_NORMALIZED_14","DOWNSIDE_VOLATILITY_20","RECENT_DRAWDOWN_60","VOLATILITY_ACCELERATION_15_60"):
        assert np.allclose(a.loc[:249,name],b.loc[:249,name],equal_nan=True)
    assert (a.max_source_timestamp_utc==a.timestamp_utc).all()


def test_cross_asset_requires_exact_timestamp_alignment_and_is_pit():
    q=bars(); s=bars(); aligned=R.cross_asset_factors(q,s)
    shifted=R.cross_asset_factors(q,bars(shift_seconds=30))
    assert len(aligned)==300 and shifted.empty
    assert (aligned.max_cross_asset_source_timestamp_utc<=aligned.decision_timestamp_utc).all()


def test_cross_asset_future_changes_do_not_change_past():
    q=bars(); s=bars(); changed=s.copy(); changed.loc[250:,"close"]+=50
    a=R.cross_asset_factors(q,s); b=R.cross_asset_factors(q,changed)
    for name in R.FAMILY_C: assert np.allclose(a.loc[:249,name],b.loc[:249,name],equal_nan=True)


def test_no_lookback_grid_and_feature_budget():
    assert len(R.FAMILY_A)==len(R.FAMILY_B)==len(R.FAMILY_C)==5
    assert len(R.FAMILY_A+R.FAMILY_B+R.FAMILY_C)==15<=18
    assert all("lookback" in R.FEATURE_DEFINITIONS[name] for name in R.FAMILY_A+R.FAMILY_B+R.FAMILY_C)


def test_candidate_gate_uses_coverage_and_same_mechanism_redundancy_only():
    frame=pd.DataFrame({name:np.arange(100,dtype=float) for name in R.FAMILY_A+R.FAMILY_B+R.FAMILY_C})
    table,approved,_=R.gate_candidates(frame)
    assert set(table.status)<= {"APPROVED","REJECTED"}
    assert sum(map(len,approved.values()))<=18
    rejected=table.loc[table.status.eq("REJECTED")]
    assert rejected.rejection_reason.str.contains("REDUNDANT|COVERAGE").all()


def test_manifest_freezes_and_mutation_fails_closed(tmp_path):
    p=tmp_path/"manifest.json"; digest=R.freeze_manifest(p,{"x":1}); R.guard_manifest(p,digest)
    p.write_text('{"x":2}\n',encoding='utf-8')
    with pytest.raises(R.R30BStop,match="STOP_FEATURE_MANIFEST_MUTATED_AFTER_FREEZE"): R.guard_manifest(p,digest)


def test_arm_membership_is_exact_ablation():
    approved={k:list(v) for k,v in R.FAMILY_NAMES.items()}; arms=R.arm_feature_sets(approved)
    assert tuple(arms["ARM_0"])==R.BASELINE_FEATURES
    assert set(arms["ARM_A"])-set(R.BASELINE_FEATURES)==set(R.FAMILY_A)
    assert set(arms["ARM_B"])-set(R.BASELINE_FEATURES)==set(R.FAMILY_B)
    assert set(arms["ARM_C"])-set(R.BASELINE_FEATURES)==set(R.FAMILY_C)
    assert set(arms["ARM_ALL"])-set(R.BASELINE_FEATURES)==set(R.FAMILY_A+R.FAMILY_B+R.FAMILY_C)
    assert set(arms)==set(R.ARM_ORDER)
    for features in arms.values():
        mask=[feature in ("symbol_code","session_code") for feature in features]
        assert len(mask)==len(features) and sum(mask)==2


def test_target_split_hgb_and_cost_contracts_unchanged():
    assert R.file_sha256(R.TARGET_CONTRACT)==R.TARGET_CONTRACT_SHA256
    target=R.read_json(R.TARGET_CONTRACT)
    assert target["TRANSACTION_COST_DECIMAL"]==.002
    assert target["PRIMARY_TARGET"]["COMPARATOR"]==">"
    split=R.read_json(R.R30A_SPLIT_IDENTITY)
    assert split["SPLIT_CONTRACT_SHA256"]==R.SPLIT_CONTRACT_SHA256 and split["FOLD_COUNT"]==5


def test_corporate_action_target_reused_and_preentry_excluded():
    identity=R.read_json(R.R30A_DATA_IDENTITY)
    assert identity["TARGET_RECONCILIATION"]["pre_entry_noncapturable_excluded_count"]==1
    assert identity["TARGET_RECONCILIATION"]["valid_target_row_count"]==1197
    assert identity["ETF_MANIFEST_SHA256"]=="1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331"


def test_no_final_holdout_and_no_data_root_writes():
    source=SCRIPT.read_text(encoding='utf-8')
    assert "FINAL_CONFIRMATION_DATA_USED\":False" in source
    assert "DATA_ROOT_WRITE_COUNT\":0" in source
    assert "GridSearchCV" not in source and "RandomizedSearchCV" not in source and "Optuna" not in source
    assert "StandardScaler" not in source and "SimpleImputer" not in source
    assert not (R.SOURCE_ROOT/"results").exists()


def test_baseline_features_are_exact_and_never_removed():
    identity=R.read_json(R.R30A_FEATURE_IDENTITY)
    assert identity["FEATURE_NAMES"]==list(R.BASELINE_FEATURES)
    assert identity["FEATURE_MANIFEST_SHA256"]==R.BASELINE_FEATURE_MANIFEST_SHA256


def test_head_column_access_filters_up_down_without_method_leakage():
    frame=pd.DataFrame({"head":["UP","DOWN"],"value":[1,2]})
    assert callable(frame.head)
    up=R.select_direction_rows(frame,"UP"); down=R.select_direction_rows(frame,"DOWN")
    assert up["head"].tolist()==["UP"]
    assert down["head"].tolist()==["DOWN"]
    assert not callable(up["head"]) and not callable(down["head"])
