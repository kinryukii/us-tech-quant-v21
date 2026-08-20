from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT=Path(__file__).parents[2]/"scripts"/"run"/"fast3_r30c_downside_severity_audit.py"
SPEC=importlib.util.spec_from_file_location("r30c",SCRIPT); R=importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def sample(n=100):
    raw=np.linspace(-.1,.1,n); loss=np.maximum(-raw,0); t4=np.log1p(loss)
    return pd.DataFrame({"candidate_id":[f"c{i:03}" for i in range(n)],"decision_timestamp_utc":pd.date_range("2020-01-01",periods=n,freq="h",tz="UTC"),"raw_net20":raw,"actual_loss":loss,"T4_DOWNSIDE_SEVERITY":t4,"pred_t4":t4})


def test_t4_formula_exact_profitable_zero_losing_positive_natural_log():
    raw=pd.Series([.1,0,-.1,-.5]); loss,t4=R.make_t4(raw)
    assert loss.tolist()==[0,0,.1,.5]
    assert np.allclose(t4,[0,0,np.log1p(.1),np.log1p(.5)])


def test_t4_contract_has_no_threshold_clipping_or_transformation_search():
    c=R.t4_contract("fixed")
    assert c["TARGET_FORMULA"]=="log1p(max(-net20,0))"
    assert c["CLIPPING"] is c["WINSORIZATION"] is c["LOSS_THRESHOLD_SEARCH"] is c["TRANSFORMATION_SEARCH"] is False
    assert c["FINAL_CONFIRMATION_DATA_USED"] is False


def test_t4_contract_freeze_and_mutation_fail_closed(tmp_path):
    p=tmp_path/"t4.json"; digest=R.freeze_t4_contract(p,"fixed"); R.guard_t4_contract(p,digest)
    p.write_text(p.read_text()+" ",encoding="utf-8")
    with pytest.raises(R.R30CStop,match="STOP_T4_TARGET_CONTRACT_MUTATED_AFTER_FREEZE"): R.guard_t4_contract(p,digest)


def test_fixed_deciles_low_to_high_and_loss_monotonicity():
    dec=R.risk_deciles(sample(),"ARM_ALL")
    assert dec.risk_decile.tolist()==list(range(1,11))
    assert R.decile_metrics(dec)["decile_actual_loss_spearman"]>0
    assert R.decile_metrics(dec)["decile_mean_net20_spearman"]<0


def test_fixed_cohort_counts_are_50_30_20_10_and_high20_10():
    c=R.risk_cohorts(sample(101),"ARM_ALL")
    assert c.cohort.tolist()==["LOWEST_RISK_50%","LOWEST_RISK_30%","LOWEST_RISK_20%","LOWEST_RISK_10%","HIGHEST_RISK_20%","HIGHEST_RISK_10%"]
    assert c["count"].tolist()==[51,31,21,11,21,11]


def test_single_diagnostic_cell_is_exact_intersection():
    frame=sample(); t1=frame[["candidate_id"]].copy(); t1["pred_t1"]=np.arange(len(t1))/len(t1)
    top,cell=R.diagnostic_cell(t1,frame)
    assert top["count"]==20 and cell["DIAGNOSTIC_ONLY"] and cell["NOT_A_FROZEN_TRADING_RULE"]
    assert 0<=cell["count"]<=20


def test_authoritative_hashes_and_feature_arms_unchanged():
    assert R.file_sha256(R.TARGET_CONTRACT)==R.TARGET_CONTRACT_SHA256
    assert R.file_sha256(R.R30B_MANIFEST)==R.R30B_FEATURE_MANIFEST_SHA256
    manifest=R.read_json(R.R30B_MANIFEST)
    assert len(manifest["arms"]["ARM_ALL"])==29 and tuple(manifest["arms"]["ARM_ALL"][:14])==R.BASELINE_FEATURES


def test_split_and_hgb_contract_are_reused():
    split=R.read_json(R.R30A_SPLIT_IDENTITY)
    assert split["SPLIT_CONTRACT_SHA256"]==R.SPLIT_CONTRACT_SHA256 and split["FOLD_COUNT"]==5
    source=SCRIPT.read_text(encoding="utf-8")
    assert "HistGradientBoostingRegressor" in source and "HistGradientBoostingClassifier" not in source
    assert "GridSearchCV" not in source and "Optuna" not in source


def test_corporate_action_normalized_target_reused():
    identity=R.read_json(R.R30A_DATA_IDENTITY)
    assert identity["TARGET_RECONCILIATION"]["valid_target_row_count"]==1197
    assert identity["TARGET_RECONCILIATION"]["pre_entry_noncapturable_excluded_count"]==1
    assert identity["ETF_MANIFEST_SHA256"]=="1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331"


def test_no_new_features_no_t1_retrain_no_final_holdout_or_data_writes():
    source=SCRIPT.read_text(encoding="utf-8")
    assert '"NEW_FEATURE_COUNT":0' in source and '"FEATURE_DEFINITION_CHANGES":0' in source
    assert '"FINAL_CONFIRMATION_DATA_USED":False' in source and '"DATA_ROOT_WRITE_COUNT":0' in source
    assert not (R.SOURCE_ROOT/"results").exists()
