import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.risk.shared_risk_budget_r2 import (
    StateBudget, StateCache, StateBudgetError, content_hash,
)


def cache(budget=None, **updates):
    context = dict(source_identity={"id": "SYNTHETIC", "version": 1},
                   cutoff="2025-06-30T00:00:00+00:00", assets=("UID:A", "UID:B"),
                   return_coordinate="absolute5d", horizon=5, identity_epoch="epoch1")
    context.update(updates)
    return StateCache(budget or StateBudget(), **context)


def test_reserves_before_fit_exact_reuse_and_result_copy():
    c = cache()
    x = np.array([1., 2.])
    called = []
    def compute():
        assert c.budget.learned_total == 1
        called.append(True)
        return {"covariance": x.copy()}
    first = c.learn("covariance", "LW", x, compute)
    first["covariance"][0] = 999
    second = c.learn("covariance", "LW", x, compute)
    assert called == [True]
    assert second["covariance"][0] == 1
    assert c.budget.snapshot()["counts"]["covariance"] == 1


def test_failure_no_refund_no_retry_and_cap_stops_before_callback():
    c = cache(StateBudget(limit=1))
    def fail():
        raise RuntimeError("synthetic failure")
    with pytest.raises(RuntimeError):
        c.learn("jackknife_subfit", "jk0", [1], fail)
    assert c.budget.learned_total == 1
    with pytest.raises(StateBudgetError, match="NO_RETRY"):
        c.learn("jackknife_subfit", "jk0", [1], lambda: 2)
    with pytest.raises(StateBudgetError, match="CAP_EXCEEDED"):
        c.learn("covariance", "different", [1], lambda: pytest.fail("executed"))
    assert c.budget.events[0]["status"] == "FAILED"


@pytest.mark.parametrize("updates", [
    {"source_identity": {"id": "SYNTHETIC", "version": 2}},
    {"identity_epoch": "epoch2"}, {"assets": ("UID:B", "UID:A")},
    {"return_coordinate": "residual5d"}, {"horizon": 20}, {"cutoff": "2025-05-30T00:00:00+00:00"},
])
def test_source_version_identity_cutoff_assets_coordinate_horizon_never_reuse(updates):
    c = cache()
    c.learn("covariance", "LW", [1], lambda: [2])
    bound = c.bind(**updates)
    bound.learn("covariance", "LW", [1], lambda: [3])
    assert c.budget.learned_total == 2


def test_inputs_and_parameters_mutation_do_not_reuse():
    c = cache()
    c.learn("covariance", "LW", [1], lambda: 1, {"lambda": .94})
    c.learn("covariance", "LW", [2], lambda: 2, {"lambda": .94})
    c.learn("covariance", "LW", [2], lambda: 3, {"lambda": .95})
    assert c.budget.learned_total == 3


def test_compute_input_mutation_is_failed_without_refund():
    c = cache()
    x = [1]
    def compute():
        x.append(2)
        return 3
    with pytest.raises(StateBudgetError, match="MUTATED"):
        c.learn("scaler", "mean", x, compute)
    assert c.budget.events[0]["status"] == "FAILED"
    assert c.budget.learned_total == 1


def test_compute_parameter_mutation_is_failed_without_refund():
    c = cache()
    parameters = {"decay": .94}
    def compute():
        parameters["decay"] = .95
        return 3
    with pytest.raises(StateBudgetError, match="MUTATED"):
        c.learn("covariance", "EWMA", [1], compute, parameters)
    assert c.budget.events[0]["status"] == "FAILED"
    assert c.budget.learned_total == 1


def test_durable_callback_failure_preserves_occupancy_no_retry():
    def failure(event):
        raise OSError("synthetic durable reserve failed")
    c = cache(StateBudget(reserve_callback=failure))
    with pytest.raises(OSError):
        c.learn("covariance", "LW", [1], lambda: pytest.fail("fit started"))
    assert c.budget.events[0]["status"] == "FAILED"
    with pytest.raises(StateBudgetError, match="NO_RETRY"):
        c.learn("covariance", "LW", [1], lambda: pytest.fail("fit retried"))


def test_nested_dependency_edges_exact_reuse_and_four_jackknife_fits():
    c = cache()
    def fit():
        return c.learn("scaler", "mean", [1], lambda: 1)
    c.learn("covariance", "LW", [1], fit)
    c.learn("covariance", "tail", [1], fit)
    for j in range(4):
        c.learn("jackknife_subfit", f"deleteblock{j}", [j], lambda: 1)
    events = c.budget.events
    assert events[0]["dependencies"] == [events[1]["key"]]
    assert events[2]["dependencies"] == [events[1]["key"]]
    assert c.budget.counts["scaler"] == 1
    assert c.budget.counts["jackknife_subfit"] == 4


def test_series_index_name_frame_attrs_and_dtype_are_hash_identity():
    a = pd.Series([1., 2.], index=pd.to_datetime(["2025-01-01", "2025-01-02"]), name="QQQ")
    b = a.copy()
    b.index = pd.to_datetime(["2025-01-02", "2025-01-03"])
    assert content_hash(a) != content_hash(b)
    b = a.copy()
    b.name = "SPY"
    assert content_hash(a) != content_hash(b)
    frame = a.to_frame()
    other = frame.copy()
    other.attrs["source_version"] = 2
    assert content_hash(frame) != content_hash(other)
    assert content_hash(np.array([1.])) != content_hash(np.array([1]))


def test_2026_guard_real_activation_and_account_are_blocked():
    with pytest.raises(StateBudgetError, match="PRE2026"):
        cache(cutoff="2026-01-01T00:00:00+00:00")
    with pytest.raises(StateBudgetError, match="ACTIVATION"):
        cache(synthetic=False)
    with pytest.raises(StateBudgetError, match="ACCOUNT"):
        cache().learn("account_replay", "account", [], lambda: pytest.fail("account ran"))


def test_usage_log_records_current_calls_and_exact_reuse_without_old_direction():
    c = cache()
    c.learn("covariance", "prior_direction", [1], lambda: [2])
    c.learn("covariance", "shared_lw", [1], lambda: [3])
    old_key, shared_key = [e["key"] for e in c.budget.events]
    start = len(c.usage_log)
    same = c.bind()
    same.learn("covariance", "shared_lw", [1], lambda: pytest.fail("duplicate fit"))
    same.learn("covariance", "current_direction", [1], lambda: [4])
    current_key = c.budget.events[-1]["key"]
    assert same.usage_log is c.usage_log
    assert c.usage_log[start:] == [shared_key, current_key]
    assert old_key not in c.usage_log[start:]
    assert c.budget.learned_total == 3


def test_usage_log_retains_nested_actual_calls_and_only_keys():
    c = cache()
    start = len(c.usage_log)
    c.learn("covariance", "LW", [1], lambda:
            c.learn("scaler", "mean", [1], lambda: [2]))
    assert c.usage_log[start:] == [e["key"] for e in c.budget.events]
    assert all(isinstance(k, str) and len(k) == 64 for k in c.usage_log)


def test_cutoff_utc_cross_2026_and_naive_are_blocked():
    with pytest.raises(StateBudgetError, match="PRE2026"):
        cache(cutoff="2025-12-31T23:30:00-05:00")
    with pytest.raises(StateBudgetError, match="TIMEZONE_AWARE"):
        cache(cutoff="2025-06-30T00:00:00")
    with pytest.raises(StateBudgetError, match="TIMEZONE_AWARE"):
        cache(cutoff="2025-06-30")


def test_equivalent_cutoff_timezones_canonicalize_for_exact_reuse():
    c = cache(cutoff="2025-06-30T00:00:00Z")
    c.learn("covariance", "LW", [1], lambda: [2])
    offset = c.bind(cutoff="2025-06-29T20:00:00-04:00")
    offset.learn("covariance", "LW", [1], lambda: pytest.fail("duplicate equivalent instant"))
    assert c.context["cutoff"] == offset.context["cutoff"] == "2025-06-30T00:00:00+00:00"
    assert c.budget.learned_total == 1



def test_mechanism_requires_explicit_mode_durable_callback_and_source_binding():
    with pytest.raises(StateBudgetError, match="DURABLE_RESERVATION"):
        cache(synthetic=False, mechanism=True)
    b = StateBudget(reserve_callback=lambda event: None)
    with pytest.raises(StateBudgetError, match="SOURCE_BINDING"):
        cache(b, synthetic=False, mechanism=True)
    with pytest.raises(StateBudgetError, match="DISTINCT"):
        cache(b, synthetic=True, mechanism=True)
    with pytest.raises(StateBudgetError, match="BOOLEAN"):
        cache(b, synthetic=1)


def test_dummy_mechanism_reservation_is_not_labeled_synthetic_and_bind_keeps_mode():
    reserved = []
    b = StateBudget(limit=2, reserve_callback=reserved.append)
    c = cache(b, synthetic=False, mechanism=True,
              source_identity={"id": "LOCAL_DUMMY_MECHANISM", "version": "v1", "sha256": "a"*64})
    result = c.learn("scaler", "dummy_operation", [1], lambda: [2])
    bound = c.bind()
    assert result == bound.learn("scaler", "dummy_operation", [1], lambda: pytest.fail("duplicate"))
    assert len(reserved) == b.learned_total == 1
    assert reserved[0]["synthetic"] is False and reserved[0]["mechanism"] is True
    assert reserved[0]["status"] == "RESERVED"
    assert b.events[0]["synthetic"] is False and b.events[0]["mechanism"] is True
    assert bound.context["mechanism"] is True and bound.context["synthetic"] is False
    assert b.snapshot()["authority"] == "EXISTING_LIFECYCLE_MECHANISM_RESERVATIONS"


def test_mechanism_reservation_failure_keeps_consumed_budget_and_blocks_retry():
    def fail(event):
        assert event["synthetic"] is False and event["mechanism"] is True
        raise OSError("local dummy durable failure")
    b = StateBudget(limit=1, reserve_callback=fail)
    c = cache(b, synthetic=False, mechanism=True,
              source_identity={"id": "LOCAL_DUMMY_MECHANISM", "version": "v1", "sha256": "a"*64})
    with pytest.raises(OSError):
        c.learn("covariance", "dummy_covariance", [1], lambda: pytest.fail("not reserved"))
    with pytest.raises(StateBudgetError, match="NO_RETRY"):
        c.learn("covariance", "dummy_covariance", [1], lambda: pytest.fail("retry"))
    assert b.learned_total == 1 and b.events[0]["status"] == "FAILED"


def test_mechanism_cannot_drop_durable_callback_after_binding():
    b = StateBudget(reserve_callback=lambda event: None)
    c = cache(b, synthetic=False, mechanism=True,
              source_identity={"id": "LOCAL_DUMMY_MECHANISM", "version": "v1", "sha256": "a"*64})
    b.reserve_callback = None
    with pytest.raises(StateBudgetError, match="DURABLE_RESERVATION"):
        c.learn("scaler", "dummy_operation", [1], lambda: pytest.fail("unreserved"))
    assert b.learned_total == 0
