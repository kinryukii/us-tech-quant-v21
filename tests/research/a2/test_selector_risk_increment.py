"""Synthetic-only PIT risk augmentation and byte-bound score reuse checks."""
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import selector_account_compare as account
from scripts.research.a2.risk import joint_risk_estimators as canonical
from scripts.research.a2.training import selector_risk_features as risk


def history():
    dates = pd.bdate_range("2022-09-01", periods=80)
    rows = [(d, name, "UID:" + name, (i + 1) * scale)
            for i, d in enumerate(dates) for name, scale in [("A", .0001), ("B", -.0002)]]
    rows += [(dates[0], "OLD", "UID:OLD", .01)]
    return pd.DataFrame(rows, columns=["signal_date", "ticker", "security_uid", "ret_1d"])


def bundle(method="SCOV"):
    return SimpleNamespace(status="FITTED", method_id=method, estimated_assets=("A", "B"),
        covariance=np.array([[.04, -.015], [-.015, .01]]), fallback_variance=.09,
        specification={"fit_cutoff": "2023-01-01"},
        fitted_state={"return_unit": risk.UNIT, "return_horizon_sessions": 1})


def test_annual_cutoff_future_rows_cannot_change_members_returns_or_identity():
    before = history()
    table, identity = risk.annual_returns(before, "2023-01-01")
    future = pd.DataFrame({"signal_date": pd.to_datetime(["2023-01-01", "2023-01-03"]),
        "ticker": ["FUTURE", "A"], "security_uid": ["UID:FUTURE", "UID:A"],
        "ret_1d": [1000., -1000.]})
    extended = pd.concat([before, future], ignore_index=True)
    extended["unused_target"] = np.inf
    actual, metadata = risk.annual_returns(extended, "2023-01-01")
    pd.testing.assert_frame_equal(actual, table)
    assert metadata == identity
    assert list(table.columns) == ["A", "B", "OLD"]
    assert table["OLD"].isna().all()  # Previously legal names are not silently removed.
    assert len(table) == 63 and table.index.max() < pd.Timestamp("2023-01-01")
    assert identity["labels_used"] is False and identity["future_membership_used"] is False
    assert identity["return_horizon_sessions"] == 1 and identity["eligibility_upgraded"] is False


def test_annual_returns_require_63_prior_feature_sessions():
    short = history().loc[lambda x: x.signal_date.isin(sorted(x.signal_date.unique())[:62])]
    with pytest.raises(ValueError, match="EXACT63"):
        risk.annual_returns(short, "2023-01-01")


@pytest.mark.parametrize("bad_key", ["ticker", "security_uid"])
def test_annual_returns_reject_duplicate_prior_keys(bad_key):
    frame = history()
    extra = frame.iloc[[0]].copy()
    extra["ticker"] = "NEW" if bad_key == "security_uid" else "A"
    extra["security_uid"] = "UID:A" if bad_key == "security_uid" else "UID:OTHER"
    with pytest.raises(ValueError, match="DUPLICATE_TICKER_UID"):
        risk.annual_returns(pd.concat([frame, extra]), "2023-01-01")


@pytest.mark.parametrize("cutoff", ["2026-01-02", pd.Timestamp("2023-01-01", tz="UTC"), pd.NaT])
def test_annual_returns_reject_invalid_fit_clock(cutoff):
    with pytest.raises(ValueError, match="INVALID_PRE2026_CUTOFF"):
        risk.annual_returns(history(), cutoff)


def test_known_unknown_projection_matches_canonical_dense_equal_pool():
    fitted = bundle()
    requested = ["UNKNOWN", "B", "A"]
    dense, metadata = canonical.risk_matrix(fitted, requested, return_metadata=True)
    weight = np.full(3, 1 / 3)
    expected = np.column_stack([np.sqrt(np.diag(dense)), dense @ weight / np.sqrt(weight @ dense @ weight),
                                [1., 0., 0.]])
    actual = risk.project(fitted, requested)
    np.testing.assert_allclose(actual, expected, rtol=1e-13, atol=1e-15)
    assert metadata["unknown_assets"] == ["UNKNOWN"]
    assert actual[1, 1] < 0  # Legal negative covariance contributions must survive.
    np.testing.assert_array_equal(fitted.covariance, [[.04, -.015], [-.015, .01]])


def projection_keys():
    return pd.DataFrame({"signal_date": pd.to_datetime(["2023-01-03"] * 2 + ["2023-01-04"] * 2),
        "ticker": ["A", "UNKNOWN", "B", "UNKNOWN"], "security_uid": ["UID:A", "UID:U", "UID:B", "UID:U"]},
        index=[17, 3, 70, 20])


def test_frame_projection_keeps_all_uid_keys_and_uses_each_current_pool():
    keys = projection_keys()
    out = risk.frame_features(bundle(), keys, 2023, "SCOV")
    pd.testing.assert_frame_equal(out[["signal_date", "ticker", "security_uid"]], keys)
    columns = ["SCOV__marginal_sigma", "SCOV__pool_covariance_normalized", "SCOV__unknown_flag"]
    for _, group in keys.groupby("signal_date", sort=True):
        expected = risk.project(bundle(), group.ticker.tolist())
        np.testing.assert_allclose(out.loc[group.index, columns].to_numpy(float), expected)
    assert out.risk_unknown_fallback.tolist() == [False, True, False, True]
    assert out.risk_asset_observed.tolist() == [True, False, True, False]
    assert not out.eligibility_upgraded.any()
    assert out.risk_cutoff.eq(pd.Timestamp("2023-01-01")).all()


def test_histvol_is_exact_diag_projection_alias():
    fitted = bundle("DIAG")
    fitted.covariance = np.diag([.04, .01])
    plain = risk.frame_features(fitted, projection_keys(), 2023, "DIAG")
    alias = risk.frame_features(fitted, projection_keys(), 2023, "HISTVOL")
    for suffix in ["marginal_sigma", "pool_covariance_normalized", "unknown_flag"]:
        np.testing.assert_array_equal(plain["DIAG__" + suffix], alias["HISTVOL__" + suffix])
    assert alias.risk_estimator_method.eq("DIAG").all()
    assert alias.risk_method.eq("HISTVOL").all()


@pytest.mark.parametrize("bad_key", ["ticker", "security_uid"])
def test_frame_projection_rejects_duplicate_keys(bad_key):
    keys = projection_keys().iloc[:2].copy()
    keys.iloc[1, keys.columns.get_loc(bad_key)] = keys.iloc[0][bad_key]
    with pytest.raises(ValueError, match="DUPLICATE_TICKER_UID"):
        risk.frame_features(bundle(), keys, 2023, "SCOV")


@pytest.mark.parametrize("date", ["2022-12-30", "2023-01-01", "2024-01-01"])
def test_frame_projection_rejects_pre_fit_equal_fit_and_next_year_dates(date):
    keys = projection_keys().iloc[[0]].copy()
    keys["signal_date"] = pd.Timestamp(date)
    with pytest.raises(ValueError, match="CLOCK_NOT_STRICTLY_AFTER"):
        risk.frame_features(bundle(), keys, 2023, "SCOV")


def test_frame_projection_rejects_wrong_annual_bundle_and_aware_dates():
    fitted = bundle()
    fitted.specification["fit_cutoff"] = "2022-01-01"
    with pytest.raises(ValueError, match="ANNUAL_FIT_CUTOFF"):
        risk.frame_features(fitted, projection_keys(), 2023, "SCOV")
    keys = projection_keys()
    keys["signal_date"] = keys.signal_date.dt.tz_localize("UTC")
    with pytest.raises(ValueError, match="NONNULL_NAIVE"):
        risk.frame_features(bundle(), keys, 2023, "SCOV")


def write_freeze(run, bindings):
    freeze = run / "DESIGN_FREEZE.json"
    freeze.write_text(json.dumps({"score_reuse": bindings}), encoding="utf-8")
    (run / "DESIGN_FREEZE_SHA.json").write_text(
        json.dumps({"sha256": hashlib.sha256(freeze.read_bytes()).hexdigest()}), encoding="utf-8")


@pytest.fixture
def borrowed(tmp_path, monkeypatch):
    backtests = tmp_path / "backtests"
    run = backtests / "new"
    run.mkdir(parents=True)
    source = backtests / "parent" / "synthetic.parquet"
    source.parent.mkdir()
    source.write_bytes(b"SYNTHETIC BYTES ONLY; NOT A RESEARCH PARQUET")
    cid = "synthetic_ridge"
    binding = {cid: {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
    write_freeze(run, binding)
    monkeypatch.setattr(account, "resolve", lambda *args, **kwargs: SimpleNamespace(backtest_root=backtests))
    return run, source, cid, binding


def test_borrowed_score_path_is_byte_bound_without_copy(borrowed):
    run, source, cid, _ = borrowed
    assert account.score_path(run, cid) == source.resolve()
    assert not (run / "predictions").exists()


@pytest.mark.parametrize("mutation,error", [
    ("borrowed_bytes", "BORROWED_SCORE_IDENTITY_CHANGED"),
    ("frozen_descriptor", "BORROWED_SCORE_FREEZE_CHANGED"),
    ("expected_score_sha", "BORROWED_SCORE_IDENTITY_CHANGED"),
    ("outside_backtest_root", "BORROWED_SCORE_IDENTITY_CHANGED"),
])
def test_borrowed_guard_rejects_changes_before_score_row_reader(borrowed, monkeypatch, mutation, error):
    run, source, cid, binding = borrowed
    if mutation == "borrowed_bytes":
        source.write_bytes(b"CHANGED SYNTHETIC BYTES")
    elif mutation == "frozen_descriptor":
        with (run / "DESIGN_FREEZE.json").open("a", encoding="utf-8") as stream:
            stream.write(" ")
    elif mutation == "expected_score_sha":
        binding[cid]["sha256"] = "0" * 64
        write_freeze(run, binding)
    else:
        outside = run.parent.parent / "outside.parquet"
        outside.write_bytes(source.read_bytes())
        binding[cid]["path"] = str(outside)
        write_freeze(run, binding)
    monkeypatch.setattr(account, "pre2026", lambda *a, **kw: pytest.fail("Score rows read before identity rejection"))
    with pytest.raises(ValueError, match=error):
        account.score_panel(run, cid)


def test_borrowed_path_requires_freeze_sha_receipt(borrowed):
    run, _, cid, _ = borrowed
    (run / "DESIGN_FREEZE_SHA.json").unlink()
    with pytest.raises(FileNotFoundError):
        account.score_path(run, cid)


def test_unborrowed_candidate_uses_local_score_path(borrowed):
    run, _, _, _ = borrowed
    assert account.score_path(run, "new_risk_role") == run / "predictions/scores_new_risk_role_pre2026.parquet"



def test_bounded_diag_fit_spawns_child_and_returns_without_artifacts(tmp_path, monkeypatch):
    import multiprocessing as mp
    import os
    from scripts.research.a2.training import selector_risk_challenge as runner

    dates = pd.bdate_range(end="2022-12-30", periods=63)
    x = np.arange(63, dtype=float)
    table = pd.DataFrame({"A": np.sin(x) * .01, "B": np.cos(x) * .02,
                          "C": (x - 31) * .0003}, index=dates)
    params = runner.risk_identity(table, pd.Timestamp("2023-01-01"))
    context = mp.get_context("spawn")
    workers = []

    def process(**kwargs):
        worker = context.Process(**kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(runner.mp, "get_context",
                        lambda name: SimpleNamespace(Pipe=context.Pipe, Process=process))
    monkeypatch.chdir(tmp_path)
    result = runner.bounded_risk_fit("DIAG", table, None, params, timeout=30)
    assert result.status == "FITTED" and result.method_id == "DIAG"
    assert result.estimated_assets == ("A", "B", "C")
    np.testing.assert_allclose(result.covariance, np.diag(table.var(ddof=1)), rtol=1e-12)
    assert all(result.specification[k] == value for k, value in params.items())
    assert result.fitted_state["return_unit"] == risk.UNIT
    assert len(workers) == 1 and workers[0].pid != os.getpid()
    assert workers[0].exitcode == 0 and not workers[0].is_alive()
    assert not list(tmp_path.iterdir())
