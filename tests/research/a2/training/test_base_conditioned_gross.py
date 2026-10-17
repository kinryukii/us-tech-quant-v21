"""Synthetic adapter checks; no fit, real arrays or account execution."""
from types import SimpleNamespace
import importlib.metadata

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import base_conditioned_gross as g


def inputs():
    x = np.ones((3, 32))
    x[:, 0] = [2., 10., 100.]
    x[:, g.owner.inputs.FEATURES.index("realized_vol_20d")] = [.1, .2, .9]
    return x, np.array([3., 7., 100.])


def rows(**overrides):
    kwargs = dict(signal_date="2024-01-02",
                  label_mature_dates=["2024-01-10"] * 3, cutoff="2024-02-01")
    kwargs.update(overrides)
    return g.training_rows([.6, .2, 0], *inputs(), [.1, -.1, np.nan], **kwargs)


def model(monkeypatch, probabilities):
    """Exercise the real probability-to-grid decoder with a synthetic estimator."""
    names = g.FEATURES + tuple(c + "__missing" for c in g.FEATURES)
    estimator = SimpleNamespace(
        classes_=np.arange(5),
        predict_proba=lambda x: np.tile(probabilities, (len(x), 1)))
    metadata = dict(source_sha256=g.models.source_sha256(),
                    native_source_sha256=g.models.NATIVE_SHA256,
                    seed=g.models.SEED, specifications=g.models.specifications(),
                    input_features=names,
                    sklearn_version=importlib.metadata.version("scikit-learn"))
    monkeypatch.setattr(g.models, "_native", lambda dependencies: None)
    return g.models.Model("gross", "tree", estimator, None, names, (), metadata)


def test_weighted_features_preserve_base_cash_and_ignore_zero_weight_names():
    ref = g.aggregate_reference([.6, .2, 0], *inputs())
    assert ref["base_tradable_gross"] == pytest.approx(.8)
    assert ref["mean_ret_1d"] == pytest.approx(4.)
    assert ref["raw_score_mean"] == pytest.approx(4.)
    assert ref["raw_score_std"] == pytest.approx(np.sqrt(3))
    assert ref["raw_score_width"] == 4.
    assert ref["diagonal_vol_proxy"] == pytest.approx(np.hypot(.06, .04))


def test_missing_features_keep_native_missing_flags_without_support_shrink():
    x, score = inputs()
    x[0, 0], score[1] = np.nan, np.nan
    ref = g.aggregate_reference([.6, .2, 0], x, score)
    frame = pd.DataFrame([dict(ref, gross_previous_proxy=1.)])
    encoded, names = g.owner.encode_features(frame, g.FEATURES)
    assert np.isnan(ref["mean_ret_1d"])
    assert np.isnan(ref["raw_score_mean"])
    assert encoded[0, names.index("mean_ret_1d")] == 0
    assert encoded[0, names.index("mean_ret_1d__missing")] == 1


def test_full_investment_reduces_to_original_r7_target():
    r = np.array([-.2, -.01, 0., .03, .2])
    prior = g.GRID
    np.testing.assert_allclose(g.gross_utilities(r, 1., prior),
                               g.owner.gross_utilities(r, prior), rtol=1e-14, atol=1e-16)
    np.testing.assert_array_equal(g.gross_targets(r, 1., prior),
                                  g.owner.gross_targets(r, prior))


def test_training_uses_unnormalised_return_and_all_five_prior_requests():
    frame = rows()
    assert frame.shape[0] == 5
    np.testing.assert_array_equal(frame.gross_previous_proxy, g.GRID)
    np.testing.assert_allclose(frame.basket_y, .04)
    np.testing.assert_allclose(frame.base_tradable_gross, .8)
    expected = (.5 * .04 - .001 * .8 * abs(.5 - 1)
                - .001 * .5 * (.8 + .04) - 5 * (.5 * .04) ** 2)
    assert g.gross_utilities(.04, .8, 1.)[2] == pytest.approx(expected)


def test_all_cash_has_no_fabricated_labels():
    assert g.training_rows([0, 0], None, None, None, signal_date="2024-01-02",
                           label_mature_dates=None, cutoff="2024-02-01").empty
    with pytest.raises(ValueError, match="NONEMPTY"):
        g.gross_utilities(0, 0, 1)


@pytest.mark.parametrize("cutoff,maturity", [
    ("2024-01-10", "2024-01-10"),
    ("2026-01-02", "2024-01-10"),
    ("2024-02-01", "2024-01-01"),
])
def test_maturity_and_hard_boundary_fail_closed(cutoff, maturity):
    with pytest.raises(ValueError):
        rows(cutoff=cutoff, label_mature_dates=[maturity] * 3)


def test_missing_required_label_never_shrinks_target_basket():
    with pytest.raises(ValueError, match="ALL_BASE_LABELS"):
        g.training_rows([.6, .2, 0], *inputs(), [.1, np.nan, .1],
                        signal_date="2024-01-02", label_mature_dates=["2024-01-10"] * 3,
                        cutoff="2024-02-01")


@pytest.mark.parametrize("weights", [[-.1, .2, 0], [.8, .4, 0], [np.nan, .2, 0]])
def test_invalid_base_weights_rejected(weights):
    with pytest.raises(ValueError, match="BASE_WEIGHTS"):
        g.aggregate_reference(weights, *inputs())


def test_predict_reuses_original_argmax_not_probability_mean(monkeypatch):
    fitted = model(monkeypatch, [.01, .51, .01, .01, .46])
    ref = g.aggregate_reference([.6, .2, 0], *inputs())
    assert g.predict_gross(fitted, ref, 1.) == .25
    fitted.features = tuple(reversed(fitted.features))
    with pytest.raises(ValueError, match="FEATURE_SCHEMA"):
        g.predict_gross(fitted, ref, 1.)


def context(paths=("one", "two"), day="2024-01-02"):
    n = len(paths)
    return SimpleNamespace(
        signal_date=pd.Timestamp(day), path_ids=paths,
        current_units=np.ones((n, 3)),
        reserved_mask=np.zeros((n, 3), bool),
        decision_mask=np.ones((n, 3), bool),
        sell_restricted=np.zeros((n, 3), bool))


def test_overlay_recomputes_live_targets_and_keeps_paths_independent(monkeypatch):
    half = model(monkeypatch, [0, 0, 1, 0, 0])
    quarter = model(monkeypatch, [0, 1, 0, 0, 0])
    calls = []
    def base(di, ctx):
        calls.append(ctx.current_units.copy())
        return g.TargetDecision(np.array([[.6, .2, 0], [.4, .2, 0]]),
                                explicit_mask=np.ones((2, 3), bool))
    overlay = g.BaseConditionedGrossOverlay(
        ("one", "two"), base, {"one": half, "two": quarter}, lambda *_: inputs())
    first = overlay(0, context())
    np.testing.assert_allclose(first.weights.sum(axis=1), [.4, .15])
    assert overlay.previous == {"one": .5, "two": .25}
    ctx = context(day="2024-01-03")
    ctx.current_units[0, 0] = 9
    overlay(1, ctx)
    assert calls[-1][0, 0] == 9
    with pytest.raises(ValueError, match="CAUSAL"):
        overlay(1, ctx)


def test_overlay_preserves_locked_units_and_missing_input_previous(monkeypatch):
    fitted = model(monkeypatch, [0, 0, 1, 0, 0])
    ctx = context()
    ctx.reserved_mask[0, 0] = True
    ctx.sell_restricted[0, 1] = True
    base = lambda *_: g.TargetDecision(np.array([[.4, .2, .2], [.6, .2, 0]]))
    overlay = g.BaseConditionedGrossOverlay(
        ctx.path_ids, base, dict.fromkeys(ctx.path_ids, fitted),
        lambda di, ctx, row: inputs() if row == 0 else None)
    result = overlay(0, ctx)
    np.testing.assert_allclose(result.weights, [[0, 0, .1], [0, 0, 0]])
    np.testing.assert_array_equal(result.explicit_mask, [[False, False, True], [False] * 3])
    assert overlay.previous == {"one": .5, "two": 1.}


@pytest.mark.parametrize("provider_behavior", ["missing", "raises"])
def test_cash_base_can_exit_without_model_or_gross_update(provider_behavior):
    calls = []
    def unavailable_provider(*args):
        calls.append(args)
        if provider_behavior == "raises":
            raise AssertionError("Cash target must never request gross inputs")
        return None
    ctx = context(paths=("one",))
    overlay = g.BaseConditionedGrossOverlay(
        ctx.path_ids, lambda *_: g.TargetDecision(np.zeros((1, 3))),
        {"one": None}, unavailable_provider)
    overlay.previous["one"] = .25
    result = overlay(0, ctx)
    assert result.explicit_mask.all()
    assert not result.weights.any()
    assert overlay.previous["one"] == .25
    assert calls == []


def test_fit_interface_delegates_to_existing_owner_without_actual_fit(monkeypatch):
    captured = {}
    def fake_fit(*args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return "synthetic-call-receipt"
    monkeypatch.setattr(g.models, "fit", fake_fit)
    frame = rows()
    assert g.fit_model("linear", frame, cutoff="2024-02-01") == "synthetic-call-receipt"
    assert captured["args"][:2] == ("gross", "linear")
    assert captured["args"][2].shape == (5, 78)
    np.testing.assert_allclose(captured["args"][4], 1.)
    with pytest.raises(ValueError, match="PAST_GROSS"):
        g.fit_model("linear", frame, cutoff="2024-01-10")


def test_implicit_hold_is_never_replaced_by_explicit_gross_target(monkeypatch):
    fitted = model(monkeypatch, [0, 0, 1, 0, 0])
    ctx = context(paths=("one",))
    base = lambda *_: g.TargetDecision(np.array([[.6, .2, 0]]),
                                      explicit_mask=np.array([[False, True, True]]))
    overlay = g.BaseConditionedGrossOverlay(
        ctx.path_ids, base, {"one": fitted}, lambda *_: inputs())
    result = overlay(0, ctx)
    np.testing.assert_allclose(result.weights, [[0, .1, 0]])
    np.testing.assert_array_equal(result.explicit_mask, [[False, True, True]])
    assert overlay.audit[0]["base_tradable_gross"] == pytest.approx(.2)


def test_exact_training_cutoff_is_allowed_but_label_equality_is_not(monkeypatch):
    assert g.TRAINING_CUTOFF == pd.Timestamp("2024-10-07")
    frame = rows(cutoff=g.TRAINING_CUTOFF)
    monkeypatch.setattr(g.models, "fit", lambda *args, **kwargs: "synthetic")
    assert g.fit_model("linear", frame, cutoff=g.TRAINING_CUTOFF) == "synthetic"
    with pytest.raises(ValueError, match="MATURE"):
        rows(cutoff=g.TRAINING_CUTOFF, label_mature_dates=["2024-10-07"] * 3)


@pytest.mark.parametrize("cutoff", ["2024-10-08", "2026-01-01"])
def test_late_training_cutoff_rejected_before_fit_or_empty_sample(cutoff, monkeypatch):
    def forbidden_fit(*args, **kwargs):
        raise AssertionError("No fit may start after the six-combination cutoff")
    monkeypatch.setattr(g.models, "fit", forbidden_fit)
    with pytest.raises(ValueError, match="PAST_BASE"):
        rows(cutoff=cutoff)
    with pytest.raises(ValueError, match="PAST_GROSS"):
        g.fit_model("linear", rows(), cutoff=cutoff)
    with pytest.raises(ValueError, match="PAST_BASE"):
        g.training_rows([0], None, None, None, signal_date="2024-01-02",
                        label_mature_dates=None, cutoff=cutoff)
