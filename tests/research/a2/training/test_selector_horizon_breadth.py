"""Synthetic invariants for fixed-X/fixed-key target breadth; no real data imports."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_horizon_breadth as h

def frames():
    dates=pd.date_range("2022-01-03",periods=50,freq="B")
    train=pd.DataFrame([dict(signal_date=d,ticker=f"S{i}",security_uid=f"ID{i}",target_end_date=d+pd.Timedelta(days=30),target=.025) for d in dates for i in range(4)])
    labels=train[["signal_date","ticker","security_uid"]].copy()
    for days,y in zip((3,5,10,20),(.01,.02,.03,.04)):
        labels[f"ER_{days}D"]=y
        labels[f"target_end_date_{days}d"]=train.signal_date+pd.Timedelta(days=days if days!=20 else 30)
    return train,labels

def test_exact_targets_and_common_maturity():
    tr,labels=frames()
    actual=h.attach_horizon_training(tr,labels)
    assert len(actual)==len(tr)
    assert actual.target.equals(tr.target)
    assert list(h.role_specs())==list(h.NEW_ROLES)
    assert h.role_specs()["HORIZON_ER_3D_HGB"]["training_target"]=="ER_3D"

@pytest.mark.parametrize("field",["signal_date","target_end_date_3d","target_end_date_20d"])
def test_future_label_rejected(field):
    tr,labels=frames();labels.loc[0,field]=pd.Timestamp("2026-01-02")
    with pytest.raises(ValueError,match="LABEL_BOUNDARY"):h.attach_horizon_training(tr,labels)

def test_mean_target_changed_rejected():
    tr,labels=frames();labels.loc[0,"ER_3D"]+=.1
    with pytest.raises(ValueError,match="MEAN_TARGET"):h.attach_horizon_training(tr,labels)

def test_missing_target_cannot_shrink_training():
    tr,labels=frames();labels.loc[0,"ER_5D"]=np.nan
    with pytest.raises(ValueError,match="FULL_TRAINING_KEYS"):h.attach_horizon_training(tr,labels)

def test_identity_swap_does_not_cross_bind():
    tr,labels=frames()
    labels.loc[[0,1],"security_uid"]=labels.loc[[1,0],"security_uid"].to_numpy()
    with pytest.raises(ValueError,match="FULL_TRAINING_KEYS"):h.attach_horizon_training(tr,labels)

def test_duplicate_identity_rejected():
    tr,labels=frames();labels=pd.concat([labels,labels.iloc[[0]]],ignore_index=True)
    with pytest.raises(ValueError,match="DUPLICATE"):h.attach_horizon_training(tr,labels)

def test_short_horizon_does_not_extend_sample():
    tr,labels=frames();train=h.attach_horizon_training(tr,labels)
    late=train.iloc[[0]].copy();late["signal_date"]=pd.Timestamp("2022-12-20")
    late["target_end_date"]=late["target_end_date_20d"]=pd.Timestamp("2023-01-20")
    for days in (3,5,10):late[f"target_end_date_{days}d"]=pd.Timestamp("2022-12-28")
    expected=h.prior.sampled(train,pd,np)
    result=h.sample_fold(pd.concat([train,late],ignore_index=True),2023,expected)
    assert result[["signal_date","ticker","security_uid"]].equals(expected[["signal_date","ticker","security_uid"]])

def test_future_append_and_target_change_do_not_change_keys():
    tr,labels=frames();train=h.attach_horizon_training(tr,labels)
    expected=h.prior.sampled(train,pd,np)
    future=train.iloc[[0]].copy()
    future["signal_date"]=pd.Timestamp("2024-01-03")
    future["target_end_date"]=pd.Timestamp("2024-02-03")
    modified=train.copy();modified["ER_3D"]=-999.
    result=h.sample_fold(pd.concat([modified,future],ignore_index=True),2023,expected)
    assert result[["signal_date","ticker","security_uid","target_end_date"]].equals(expected[["signal_date","ticker","security_uid","target_end_date"]])

def test_changed_sample_keys_are_rejected():
    tr,labels=frames();train=h.attach_horizon_training(tr,labels)
    expected=h.prior.sampled(train,pd,np);expected.loc[0,"ticker"]="SWAPPED"
    with pytest.raises(ValueError,match="SHARED_KEYS"):h.sample_fold(train,2023,expected)


@pytest.fixture
def synthetic_freeze(monkeypatch, tmp_path):
    """A complete synthetic freeze whose readers never open project artifacts."""
    from pathlib import Path

    run = (tmp_path / "synthetic_run").resolve()
    features = [f"feature_{i}" for i in range(32)]
    digest = "synthetic-design-sha"
    sources = {str(p): "synthetic-source-sha" for p in h.old.required_source_paths()}
    sources.update({
        str(Path(h.__file__).resolve()): "synthetic-source-sha",
        str(h.REPO / "scripts/research/a2/evaluation/selector_horizon_evidence.py"): "synthetic-source-sha",
    })
    pins = {
        name: {"path": str(tmp_path / f"{name}.json"), "sha256": f"synthetic-{name}-sha"}
        for name in ("physical_dag", "horizon_inputs", "native_reuse_manifest", "source_contract")
    }
    cfg = dict(research_id=h.ID, research_line="C_SELECTOR",
               design_freeze_sha256=digest,
               results_directory=str(tmp_path / "results"),
               cache_directory=str(tmp_path / "cache"))
    design = dict(research_id=h.ID, official_freeze=True, formal_freeze_applied=True,
                  roles=list(h.ROLES), role_specs=h.role_specs(), budget=dict(h.BUDGET),
                  target="MEAN_ER_3D_5D_10D_20D", seed=20260928,
                  strict_PIT_promotion_eligible=False, test2026_locked=True,
                  new2026_estimation_authorized=False, features=features,
                  fixed_features=list(features), new_fitting_years=list(h.YEARS),
                  sources=sources, **pins)
    documents = {
        str(run / "run_config.json"): cfg,
        str(run / "DESIGN_FREEZE.json"): design,
        str(run / "DESIGN_FREEZE_SHA.json"): {"sha256": digest},
        str(run / "FORMAL_FREEZE_REVIEW.json"): {"status": "PASS"},
        str(run / "FREEZE_ACTIVATION.json"): {
            "status": "PASS", "design_freeze_sha256": digest,
        },
        pins["source_contract"]["path"]: {
            "strict_PIT_promotion_eligible": False,
            "mechanism_research_eligible": True,
            "source_contract_mode": "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
        },
    }
    hashes = {str(run / "DESIGN_FREEZE.json"): digest, **sources}
    hashes.update({pin["path"]: pin["sha256"] for pin in pins.values()})

    def synthetic_read(path):
        key = str(Path(path))
        if key not in documents:
            raise AssertionError(f"Unexpected synthetic document read: {key}")
        return documents[key]

    def synthetic_sha(path):
        key = str(Path(path))
        if key not in hashes:
            raise AssertionError(f"Unexpected synthetic hash read: {key}")
        return hashes[key]

    monkeypatch.setattr(h, "readj", synthetic_read)
    monkeypatch.setattr(h, "sha", synthetic_sha)
    monkeypatch.setattr(h, "resolve", lambda repo: object())
    monkeypatch.setattr(h, "assert_safe_output_path", lambda *args, **kwargs: None)
    return run, cfg, design, documents, hashes


def test_checked_complete_synthetic_freeze_passes(synthetic_freeze):
    run, cfg, design, _, _ = synthetic_freeze
    assert h.checked(run) == (cfg, design)


@pytest.mark.parametrize("missing", [
    "selector_horizon_breadth.py", "predictors.py", "selector_horizon_evidence.py",
])
def test_checked_required_source_missing_rejected(synthetic_freeze, missing):
    from pathlib import Path

    run, _, design, _, _ = synthetic_freeze
    key = next(path for path in design["sources"] if Path(path).name == missing)
    del design["sources"][key]
    with pytest.raises(ValueError, match="FROZEN_SOURCE_CLOSURE_REQUIRED"):
        h.checked(run)


def test_checked_dag_hash_change_rejected(synthetic_freeze):
    run, _, design, _, hashes = synthetic_freeze
    hashes[design["physical_dag"]["path"]] = "changed-physical-dag-sha"
    with pytest.raises(ValueError, match="FROZEN_DAG_CHANGED"):
        h.checked(run)


@pytest.mark.parametrize("mutation", ["failed_status", "wrong_design", "missing_design"])
def test_checked_activation_mismatch_rejected(synthetic_freeze, mutation):
    run, _, _, documents, _ = synthetic_freeze
    activation = documents[str(run / "FREEZE_ACTIVATION.json")]
    if mutation == "failed_status":
        activation["status"] = "FAIL"
    elif mutation == "wrong_design":
        activation["design_freeze_sha256"] = "another-design-sha"
    else:
        activation.pop("design_freeze_sha256")
    with pytest.raises(ValueError, match="FREEZE_ACTIVATION_REQUIRED"):
        h.checked(run)
