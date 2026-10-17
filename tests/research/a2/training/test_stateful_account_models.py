"""Synthetic-only R9 adapters; reads one immutable design metadata JSON.

No account engine, provider, market, feature, y or other-route outcome file is
opened. Small Ridge fits use generated arrays and do not enter scientific 174.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import stateful_account_models as m


@pytest.fixture
def spec():
    design = json.loads(Path("D:/us-tech-quant-results/_maintenance/V24_A_ACCOUNT_STATE_DECISION_LEARNING_PRE2026_R9/R9_PREREGISTERED_DESIGN.json").read_text(encoding="utf-8"))
    return m.FrozenSpec.from_design(design)


def metadata(n=40, start="2023-01-03"):
    dates = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame(dict(row_key=[f"synthetic:{x}" for x in range(n)],
        signal_asof=dates, label_mature_date=dates+pd.Timedelta(days=8),
        label_available_at=dates+pd.Timedelta(days=9), state_qualified=True,
        label_qualified=True, matched_reference_group=True))


def batch(n=40, head=m.HEADS[0], meta=None):
    meta = metadata(n) if meta is None else meta
    rng = np.random.default_rng(10)
    x = rng.normal(size=(len(meta), 2))
    return m.HeadBatch(head, meta, x, x[:, 0]*.01, np.ones(len(meta)),
                       ("synthetic_a", "synthetic_b"), "synthetic-fixed-encoding")


class FakeEstimator:
    def __init__(self, family, failed=False):
        self.family, self.failed, self.params = family, failed, {}

    def set_params(self, **params):
        self.params.update(params)
        return self

    def fit(self, X, y, sample_weight):
        if self.failed:
            raise RuntimeError("synthetic failure")
        self.rows = len(y)
        self.mean = float(np.average(y, weights=sample_weight))
        self.n_iter_ = self.params.get("max_iter")
        self.tree_count_ = self.params.get("iterations")
        return self

    def predict(self, X):
        return np.full(len(X), self.mean)


def test_frozen_design_and_model_space(spec):
    for family in m.FAMILIES:
        model, _ = spec.model(family, "LOW")
        assert model["family"] == family
    changed = deepcopy(spec.design)
    changed["models"][0]["capacity_kwargs"]["LOW"]["alpha"] = 99
    with pytest.raises(ValueError, match="FROZEN_DESIGN_CHANGED"):
        m.FrozenSpec.from_design(changed)
    with pytest.raises(ValueError, match="OUTER_YEAR"):
        spec.fold(2023)


def test_signal_maturity_availability_and_literal_mask_fail_closed(spec):
    meta = metadata(7)
    meta.loc[1, "label_mature_date"] = pd.Timestamp("2023-10-01")
    meta.loc[2, "label_available_at"] = pd.Timestamp("2024-01-01")
    meta.loc[3, "label_mature_date"] = pd.NaT
    meta.loc[4, "signal_asof"] = pd.Timestamp("2026-01-01")
    meta["state_qualified"] = meta.state_qualified.astype(object)
    meta.loc[5, "state_qualified"] = 1
    meta.loc[6, "label_qualified"] = False
    masks = m.fold_masks(meta, spec, 2024)
    assert masks["core"].tolist() == [True, False, False, False, False, False, False]
    assert not masks["outer"][2:].any()


def test_full_legal_rows_have_no_12000_cap(spec):
    meta = metadata(13003)
    meta.signal_asof = pd.Timestamp("2023-01-03")
    meta.label_mature_date = pd.Timestamp("2023-01-11")
    meta.label_available_at = pd.Timestamp("2023-01-12")
    prepared = m.prepare_head(batch(meta=meta), spec, 2024, "core")
    assert len(prepared.row_keys) == 13003
    assert np.array_equal(prepared.y, batch(meta=meta).target)


def test_real_unadmitted_rejected_before_factory_or_numeric_batch(spec, monkeypatch):
    monkeypatch.setattr(m.native_owner, "_native", lambda _: pytest.fail("factory reached"))
    bad = m.HeadBatch(m.HEADS[0], pd.DataFrame(), object(), object(), object(), (), "")
    for admission in ({}, {"real_fit_authorized": 1}):
        budget = m.FitBudget(spec, admission=admission)
        with pytest.raises(ValueError, match="REAL_FIT_NOT_ADMITTED"):
            m.fit_head_ensemble(bad, spec, 2024, "core", "RIDGE", "LOW", budget=budget, scalers=m.SharedScalers())
        assert budget.counts()["attempts"] == 0


def test_two_small_actual_synthetic_ridge_fits_share_one_scaler(spec):
    b, budget, scalers = batch(), m.FitBudget(spec, synthetic=True), m.SharedScalers()
    low = m.fit_head_ensemble(b, spec, 2024, "core", "RIDGE", "LOW", budget=budget, scalers=scalers)
    high = m.fit_head_ensemble(b, spec, 2024, "core", "RIDGE", "HIGH", budget=budget, scalers=scalers)
    assert low.scaler is high.scaler
    assert len(scalers.complete) == 1
    assert low.metadata["training_rows"] == 40
    assert low.metadata["scientific_budget_included"] is False
    assert low.estimators[0].get_params()["alpha"] == 100
    assert high.estimators[0].get_params()["alpha"] == 1
    assert np.isfinite(low.predict(b.X)).all()
    assert budget.counts()["synthetic_fit_calls"] == 3
    assert budget.counts()["real_fit_calls"] == 0


def test_fake_native_kwargs_seeds_scaler_reuse_without_meta_fit(spec, monkeypatch):
    made = []
    def factory(family):
        estimator = FakeEstimator(family)
        made.append(estimator)
        return estimator
    monkeypatch.setattr(m.native_owner, "_native", lambda _: SimpleNamespace(estimator=factory))
    b, budget, scalers = batch(), m.FitBudget(spec, synthetic=True), m.SharedScalers()
    ridge = m.fit_head_ensemble(b, spec, 2024, "core", "RIDGE", "MID", budget=budget, scalers=scalers)
    mlp = m.fit_head_ensemble(b, spec, 2024, "core", "MLP", "LOW", budget=budget, scalers=scalers)
    cat = m.fit_head_ensemble(b, spec, 2024, "core", "CATBOOST", "LOW", budget=budget, scalers=scalers)
    tree = m.fit_head_ensemble(b, spec, 2024, "core", "HGB", "LOW", budget=budget, scalers=scalers)
    assert mlp.scaler is ridge.scaler and cat.scaler is None and tree.scaler is None
    assert [e.params["random_state"] for e in mlp.estimators] == [20260928, 20260929, 20260930]
    assert [e.params["random_seed"] for e in cat.estimators] == [20260928, 20260929, 20260930]
    assert all(e.params["early_stopping"] is False for e in mlp.estimators)
    assert cat.estimators[0].params["allow_writing_files"] is False
    assert len(made) == 8 and budget.counts()["inner_scaler"] == 1
    assert np.allclose(mlp.predict(b.X), np.mean([e.predict(b.X) for e in mlp.estimators], axis=0))
    assert mlp.metadata["calibrator_fits"] == mlp.metadata["ensemble_fits"] == 0


def test_changed_rows_weights_or_features_cannot_create_second_head_scaler(spec, monkeypatch):
    monkeypatch.setattr(m.native_owner, "_native", lambda _: SimpleNamespace(estimator=lambda f: FakeEstimator(f)))
    b, budget, scalers = batch(), m.FitBudget(spec, synthetic=True), m.SharedScalers()
    m.fit_head_ensemble(b, spec, 2024, "core", "RIDGE", "LOW", budget=budget, scalers=scalers)
    changed = deepcopy(b)
    changed.weights[0] = 2
    with pytest.raises(ValueError, match="HEAD_ROWS_WEIGHTS_OR_INPUTS_CHANGED"):
        m.fit_head_ensemble(changed, spec, 2024, "core", "HGB", "LOW", budget=budget, scalers=scalers)
    assert budget.counts()["attempts"] == 2


def test_failed_slot_counts_and_no_scientific_retry(spec, monkeypatch):
    monkeypatch.setattr(m.native_owner, "_native", lambda _: SimpleNamespace(estimator=lambda f: FakeEstimator(f, failed=True)))
    b, budget, scalers = batch(), m.FitBudget(spec, synthetic=True), m.SharedScalers()
    with pytest.raises(RuntimeError, match="synthetic failure"):
        m.fit_head_ensemble(b, spec, 2024, "core", "HGB", "LOW", budget=budget, scalers=scalers)
    assert budget.counts()["failed"] == budget.counts()["attempts"] == 1
    with pytest.raises(ValueError, match="NO_SCIENTIFIC_RETRY"):
        m.fit_head_ensemble(b, spec, 2024, "core", "HGB", "LOW", budget=budget, scalers=scalers)
    assert budget.counts()["attempts"] == 1


def test_hard_174_and_stage_component_caps_guard_before_fit(spec):
    budget = m.FitBudget(spec, synthetic=True)
    for stage, models, scalers in [("inner", 144, 6), ("outer", 18, 6)]:
        for component, count in [("model", models), ("scaler", scalers)]:
            for i in range(count):
                key = budget.start(dict(stage=stage, component=component, i=i), stage=stage, component=component)
                budget.finish(key, RuntimeError("synthetic reservation failure"))
    assert budget.counts()["attempts"] == budget.counts()["failed"] == 174
    with pytest.raises(ValueError, match="BLOCKED_BUDGET"):
        budget.start(dict(extra=True), stage="outer", component="model")
    assert budget.counts()["real_fit_calls"] == budget.counts()["synthetic_fit_calls"] == 0


def candidates(year=2024):
    return {(family, capacity):dict(outer_year=year, phase="INNER_VALIDATION", status="COMPLETE",
        head_metrics={head:dict(paired_regret=1., validation_identity=head) for head in m.HEADS})
        for family in m.FAMILIES for capacity in m.CAPACITIES}


def test_common_three_head_selection_ties_no_future_or_support_cherry_pick(spec):
    receipts = candidates()
    chosen = m.select_common_family_capacity(receipts, spec, 2024)
    assert (chosen["family"], chosen["capacity"]) == ("RIDGE", "LOW")
    receipts[("RIDGE", "HIGH")]["head_metrics"][m.HEADS[0]]["paired_regret"] = 0
    # The selection is the mean across all heads; never three different pipelines.
    chosen = m.select_common_family_capacity(receipts, spec, 2024)
    assert chosen["family"] == "RIDGE" and chosen["capacity"] == "HIGH"
    receipts[("HGB", "LOW")]["head_metrics"][m.HEADS[0]]["validation_identity"] = "changed"
    with pytest.raises(ValueError, match="VALIDATION_SUPPORT_CHANGED"):
        m.select_common_family_capacity(receipts, spec, 2024)
    with pytest.raises(ValueError, match="ALL_12"):
        m.select_common_family_capacity({}, spec, 2024)
    wrong = candidates()
    wrong[("RIDGE", "LOW")]["phase"] = "OUTER_ECONOMIC"
    with pytest.raises(ValueError, match="OUTER_OUTCOME"):
        m.select_common_family_capacity(wrong, spec, 2024)


def test_inner_paired_regret_is_date_balanced_and_requires_reference(spec):
    meta = metadata(4, "2023-10-02")
    meta.loc[1:2, "signal_asof"] = meta.loc[0, "signal_asof"]
    metric = m.date_balanced_paired_regret(meta, np.array([0., 0., 0., .4]), np.ones(4), spec, 2024)
    assert metric["paired_regret"] == .2 and metric["validation_dates"] == 2
    meta.loc[0, "matched_reference_group"] = False
    with pytest.raises(ValueError, match="MATCHED_INNER_VALIDATION"):
        m.date_balanced_paired_regret(meta, np.zeros(4), np.ones(4), spec, 2024)


@pytest.mark.parametrize("bad", [False, None, 1])
@pytest.mark.parametrize("gate", m.BASELINE_GATES)
def test_real_admission_never_accepts_composite_or_nonliteral_gate(spec, gate, bad):
    admission = {k: True for k in ["real_fit_authorized", "runtime_fit_admitted", "registry_admitted",
        "qualified_reference_state", "qualified_counterfactual_labels", "source_pins_frozen"]}
    admission["baseline_gates"] = dict.fromkeys(m.BASELINE_GATES, True)
    admission["source_slots"] = dict.fromkeys(m.SOURCE_SLOTS, True)
    admission["baseline_gates"][gate] = bad
    admission["eligible_for_selection"] = True
    budget = m.FitBudget(spec, admission=admission, on_fit_started=lambda event: True)
    with pytest.raises(ValueError, match="REAL_FIT_NOT_ADMITTED"):
        budget.admitted()
    assert budget.counts()["attempts"] == 0


def test_outer_fits_require_one_common_selected_family_capacity(spec, monkeypatch):
    monkeypatch.setattr(m.native_owner, "_native", lambda _: SimpleNamespace(estimator=lambda f: FakeEstimator(f)))
    budget, scalers = m.FitBudget(spec, synthetic=True), m.SharedScalers()
    with pytest.raises(ValueError, match="COMMON_SELECTED_PIPELINE"):
        m.fit_head_ensemble(batch(), spec, 2024, "outer", "HGB", "LOW", budget=budget, scalers=scalers)
    receipts = candidates()
    for head in m.HEADS:
        receipts[("HGB", "LOW")]["head_metrics"][head]["paired_regret"] = 0
    selection = m.select_common_family_capacity(receipts, spec, 2024)
    for head in m.HEADS:
        model = m.fit_head_ensemble(batch(head=head), spec, 2024, "outer", "HGB", "LOW",
            budget=budget, scalers=scalers, selection=selection)
        assert model.family == "HGB" and model.capacity == "LOW"
    assert budget.counts()["outer_model"] == 3 and budget.counts()["outer_scaler"] == 0
    changed = deepcopy(selection)
    changed["family"] = "RIDGE"
    with pytest.raises(ValueError, match="PIPELINE_CHANGED"):
        m.fit_head_ensemble(batch(), spec, 2024, "outer", "RIDGE", "LOW",
            budget=budget, scalers=scalers, selection=changed)


def test_fixed_epoch_mlp_warning_recorded_without_changing_final_epoch(spec, monkeypatch):
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    class FixedEpoch(FakeEstimator):
        def fit(self, X, y, sample_weight):
            result = super().fit(X, y, sample_weight)
            warnings.warn("synthetic fixed max_iter reached", ConvergenceWarning)
            return result
    monkeypatch.setattr(m.native_owner, "_native", lambda _: SimpleNamespace(estimator=lambda f: FixedEpoch(f)))
    budget = m.FitBudget(spec, synthetic=True)
    model = m.fit_head_ensemble(batch(), spec, 2024, "core", "MLP", "LOW", budget=budget, scalers=m.SharedScalers())
    assert all(e.n_iter_ == 40 for e in model.estimators)
    assert budget.counts()["failed"] == 0
    assert all(budget.attempts[k]["warnings"] for k in model.metadata["fit_identity_shas"])
