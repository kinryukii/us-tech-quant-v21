from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd

RUNNER=Path(__file__).parents[2]/"scripts/run/fast3_r33a_full_universe_payoff_decomposition.py"
spec=importlib.util.spec_from_file_location("r33a",RUNNER); r33a=importlib.util.module_from_spec(spec)
assert spec.loader is not None; spec.loader.exec_module(r33a)


def sample() -> pd.DataFrame:
    x=pd.DataFrame({"candidate_id":[f"c{i}" for i in range(100)],"decision_timestamp_utc":pd.date_range("2024-01-02T14:00:00Z",periods=100,freq="min"),
                    "pred_t1":np.arange(100,dtype=float),"raw_net20":np.where(np.arange(100)%2,.02,-.03)})
    x["trading_date"]=x.decision_timestamp_utc.dt.tz_convert(r33a.NY).dt.date.astype(str); return x


def test_expectancy_reconciliation_and_break_even_exact() -> None:
    stats=r33a.payoff_stats(pd.DataFrame({"raw_net20":[.02,.02,-.03,-.03]}))
    assert stats["expectancy_reconciliation_pass"] and np.isclose(stats["mean_net20"],-.005,rtol=0,atol=1e-15)
    assert np.isclose(stats["break_even_win_rate"],.6) and np.isclose(stats["win_rate_minus_break_even"],-.1)


def test_top_cohort_and_deciles_are_deterministic() -> None:
    x=sample(); a=r33a.top_cohort(x,20); b=r33a.top_cohort(x.iloc[::-1],20)
    assert a.candidate_id.tolist()==b.candidate_id.tolist() and len(a)==20
    dec=r33a.decile_decomposition(x); assert dec.decile.tolist()==list(range(1,11)) and dec["count"].eq(10).all()
    assert dec.expectancy_reconciliation_pass.all()


def test_tail_contribution_is_exact_and_rows_are_not_removed() -> None:
    x=pd.DataFrame({"raw_net20":[-10.,-3.,-2.,-1.,4.]})
    assert np.isclose(r33a.tail_contribution(x,20),10/16)
    assert len(x)==5 and x.raw_net20.min()==-10


def test_date_balanced_uses_equal_et_date_weight() -> None:
    x=pd.DataFrame({"trading_date":["2024-01-02"]*2+["2024-01-03"]*4,"raw_net20":[.1,-.1,.1,.1,.1,-.1]})
    stats=r33a.date_balanced_stats(x); assert stats["date_count"]==2
    assert np.isclose(stats["win_rate"],.625)


def test_mechanism_rules_are_frozen_before_run() -> None:
    full={"win_rate":.50,"mean_gain_given_win":.02,"mean_absolute_loss_given_loss":.03}
    top={"win_rate":.60,"mean_gain_given_win":.02,"mean_absolute_loss_given_loss":.04,"win_rate_minus_break_even":-.05}
    classification,_,flags=r33a.mechanism_classification(full,top,0,.5)
    assert classification=="A_WIN_PROBABILITY_EDGE_BLOCKED_PRIMARILY_BY_LOSS_SEVERITY" and flags["loss_severity_adverse"]


def test_frozen_oof_identity_no_model_calls_and_anti_bloat() -> None:
    frame,path=r33a.load_frozen_oof(); assert len(frame)==r33a.OOF_ROW_COUNT and r33a.file_sha256(path)==r33a.OOF_SHA256
    source=RUNNER.read_text(encoding="utf-8"); tree=ast.parse(source)
    forbidden=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {"fit","predict","predict_proba"}]
    assert not forbidden and "sklearn.ensemble" not in source and "GridSearch" not in source and "Optuna" not in source
    assert "dropna" not in inspect.getsource(r33a.tail_contribution)
    assert r33a.DATA_ROOT==Path(r"D:\us-tech-quant-data") and r33a.FROZEN_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert not any(RUNNER.parent.glob("*r33a*helper*.py"))
