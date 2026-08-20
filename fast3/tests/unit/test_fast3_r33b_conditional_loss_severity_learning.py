from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd

RUNNER=Path(__file__).parents[2]/"scripts/run/fast3_r33b_conditional_loss_severity_learning.py"
spec=importlib.util.spec_from_file_location("r33b",RUNNER); r33b=importlib.util.module_from_spec(spec)
assert spec.loader is not None; spec.loader.exec_module(r33b)


def synthetic() -> pd.DataFrame:
    n=100
    x=pd.DataFrame({"candidate_id":[f"c{i}" for i in range(n)],"decision_timestamp_utc":pd.date_range("2024-01-02T14:00:00Z",periods=n,freq="min"),
                    "pred_t1":np.linspace(.1,.9,n),"pred_t5":np.tile(np.linspace(.01,.1,10),10),"raw_net20":-np.tile(np.linspace(.01,.1,10),10)})
    x["abs_loss"]=-x.raw_net20; x["actual_t5"]=np.log1p(x.abs_loss); x["trading_date"]=x.decision_timestamp_utc.dt.tz_convert(r33b.NY).dt.date.astype(str); return x


def test_t5_formula_and_strict_loser_eligibility() -> None:
    net=pd.Series([-0.10,-0.01,0.0,0.02]); t5=r33b.derive_t5(net)
    assert np.isclose(t5.iloc[0],np.log1p(.10)) and np.isclose(t5.iloc[1],np.log1p(.01))
    assert t5.iloc[2:].isna().all() and not t5.iloc[2:].eq(0).any()


def test_all_validation_rows_can_receive_predictions_but_only_losses_have_target() -> None:
    net=pd.Series([-0.1,0.0,0.1]); target=r33b.derive_t5(net); predictions=pd.Series([.1,.2,.3])
    assert predictions.notna().all() and target.notna().sum()==1


def test_within_t1_conditional_ranking_and_median_split_exact() -> None:
    x=synthetic(); table,pooled,mean,median,correct,incorrect,tied=r33b.conditional_t1_audit(x)
    assert pooled>0 and mean>0 and median>0 and correct==10 and incorrect==0 and tied==0
    assert table.low_t5_count.eq(5).all() and table.high_t5_count.eq(5).all()


def test_top20_and_half_split_are_deterministic() -> None:
    x=synthetic(); a=r33b.top20_t5_split(x); b=r33b.top20_t5_split(x.iloc[::-1])
    assert len(a[0])==20 and len(a[1])==len(a[2])==10
    assert a[1].candidate_id.tolist()==b[1].candidate_id.tolist() and a[2].candidate_id.tolist()==b[2].candidate_id.tolist()


def test_authoritative_identity_same_29_features_split_and_hgb() -> None:
    r32b,r30a,summary,oof_path=r33b.validate_authority(); _,manifest,features=r32b.guard_authority()
    assert len(features)==29 and tuple(features)==tuple(json_features(r32b.FEATURE_MANIFEST))
    assert "pred_t1" not in features and r30a.HGB_PARAMS["random_state"]==1729 and len(r30a.ECONOMIC_FOLDS)==5
    assert summary["FINAL_CONFIRMATION_DATA_USED"] is False and r33b.file_sha256(oof_path)==r33b.R32B_OOF_SHA
    assert manifest["FINAL_CONFIRMATION_ROW_COUNT_IN_LABEL_LEDGER"]==0


def json_features(path: Path) -> list[str]:
    import json
    return json.loads(path.read_text(encoding="utf-8"))["arms"]["ARM_ALL"]


def test_no_t1_feature_sampling_clipping_or_extra_framework() -> None:
    source=RUNNER.read_text(encoding="utf-8"); tree=ast.parse(source)
    fit_calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="fit"]
    predict_calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="predict"]
    assert len(fit_calls)==1 and len(predict_calls)==1 and ".sample(" not in source and "GridSearch" not in source and "Optuna" not in source
    training=inspect.getsource(r33b.main)
    assert 'train&eligible&dataset["head"].eq(direction)' in training and 'model.fit' in training and 'model.predict' in training
    assert '"pred_t1" in features' in training and "np.clip" not in training and "quantile_transform" not in training
    assert '"WINSORIZATION":False' in training and '"TAIL_CLIPPING_USED":False' in training
    assert r33b.DATA_ROOT==Path(r"D:\us-tech-quant-data") and r33b.FROZEN_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert not any(RUNNER.parent.glob("*r33b*helper*.py"))
