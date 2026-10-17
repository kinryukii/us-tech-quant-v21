"""Meaningful boundary tests, independent of live accounts and source training."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


MODULE_PATH = Path(__file__).resolve().parents[4] / "scripts/research/a2/portfolio/selected_hgb.py"
spec = importlib.util.spec_from_file_location("selected_hgb_test_backend", MODULE_PATH)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def _day():
    import pandas as pd
    rows = []
    for rank in range(1, 41):
        rows.append({"signal_date": "2026-09-24", "ticker": f"T{rank}", "raw_rank": rank,
                     "raw_score": 41.0 - rank, **{name: .01 for name in backend.FEATURES if name not in ("raw_rank_strength", "raw_score_z")}})
    return pd.DataFrame(rows)


def _runtime():
    import numpy as np
    import pandas as pd
    return {"np": np, "pd": pd}


def test_module_top_level_does_not_load_scientific_runtime():
    import ast
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = {node.module.split(".")[0] for node in imports if isinstance(node, ast.ImportFrom)}
    names |= {alias.name.split(".")[0] for node in imports if isinstance(node, ast.Import) for alias in node.names}
    assert not names.intersection({"numpy", "pandas", "joblib", "sklearn", "scipy", "pyarrow", "torch"})


def test_source_hash_rejected_before_loading(tmp_path):
    path = tmp_path / "untrusted.joblib"
    path.write_bytes(b"altered bytes")
    with pytest.raises(backend.SelectedStrategyError, match="SOURCE_HASH_MISMATCH"):
        backend._verify(path, "0" * 64)


def test_day_requires_complete_ranked_features_and_one_date():
    valid, signal = backend._normalise_day(_day(), _runtime())
    assert signal == "2026-09-24" and len(valid) == 40
    with pytest.raises(backend.SelectedStrategyError, match="COMPLETE_FROZEN_FEATURES_REQUIRED"):
        backend._normalise_day(_day().drop(columns="lag_ret_09"), _runtime())
    duplicated = _day()
    duplicated.loc[39, "raw_rank"] = 39
    with pytest.raises(backend.SelectedStrategyError, match="RAW_TOP40_RANK_OR_SCORE_INVALID"):
        backend._normalise_day(duplicated, _runtime())
    future = _day()
    future.loc[0, "signal_date"] = "2026-09-25"
    with pytest.raises(backend.SelectedStrategyError, match="SINGLE_SIGNAL_DATE_REQUIRED"):
        backend._normalise_day(future, _runtime())


def test_missing_or_nonfinite_lag_is_blocked():
    day = _day()
    day.loc[0, "lag_ret_04"] = float("nan")
    with pytest.raises(backend.SelectedStrategyError, match="INCOMPLETE_OR_NONFINITE"):
        backend._normalise_day(day, _runtime())


def test_real_state_requires_signal_close_and_cash_identity():
    state = {"signal_date": "2026-09-24", "valuation_basis": "SIGNAL_CLOSE", "weights": {"A": .2}, "cash_weight": .8}
    assert backend._state(state, "2026-09-24")[:2] == ({"A": .2}, .8)
    for invalid in (dict(state, signal_date="2026-09-25"), dict(state, next_open={"A": 10}),
                    dict(state, valuation_basis="EXECUTION_OPEN")):
        with pytest.raises(backend.SelectedStrategyError, match="SAME_SIGNAL_CLOSE"):
            backend._state(invalid, "2026-09-24")
    with pytest.raises(backend.SelectedStrategyError, match="CASH_WEIGHT_IDENTITY"):
        backend._state(dict(state, cash_weight=.7), "2026-09-24")


def test_inference_keeps_original_solver_and_account_constraints(monkeypatch):
    import numpy as np
    runtime = _runtime()
    calls = []

    class Model:
        def predict(self, frame):
            assert list(frame.columns) == list(backend.FEATURES)
            return np.zeros(len(frame))

    class Optimizer:
        SPECS = {name: name for name in backend.STRATEGY_IDS}

        @staticmethod
        def solve(day, shares, values, nav, risk, strategy, signal):
            calls.append((shares.copy(), values.copy(), nav, strategy, signal))
            assert nav == 1 and values == {"OLD": .2} and shares == {"OLD": 1}
            return {"T1": .1, "OLD": .05}, {"solver_failed": False}

    runtime.update(model=Model(), q10=Model(), optimizer=Optimizer(), risk={})
    monkeypatch.setattr(backend, "_runtime", lambda root: runtime)
    state = {"signal_date": "2026-09-24", "valuation_basis": "SIGNAL_CLOSE", "weights": {"OLD": .2}, "cash_weight": .8}
    applications = backend.infer_targets(_day(), state)
    assert len(calls) == 2
    for application in applications.values():
        assert application["account_basis"] == "USER_SUPPLIED_SIGNAL_CLOSE_STATE"
        assert application["target_cash_weight"] == pytest.approx(.85)
        assert {row["ticker"]: row["action"] for row in application["rows"]} == {"OLD": "SELL", "T1": "BUY"}
        assert sum(row["target_weight"] for row in application["rows"]) + application["target_cash_weight"] == pytest.approx(1)
        assert all(0 <= row["target_weight"] <= .1 for row in application["rows"])


def test_publish_is_atomic_and_rejects_unselected_ids(tmp_path):
    package = {"schema_version": 1, "selection_basis": backend.SELECTION_BASIS,
               "strategies": {name: {} for name in backend.STRATEGY_IDS}}
    output = backend.publish(package, tmp_path / "package.json")
    assert json.loads(output.read_text(encoding="utf-8")) == package
    assert not list(tmp_path.glob("*.tmp"))
    package["strategies"]["OTHER"] = {}
    with pytest.raises(backend.SelectedStrategyError, match="PACKAGE_IDENTITY_INVALID"):
        backend.publish(package, output)


def test_failed_current_integrity_never_falls_back_to_a_different_signal(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "verify_frozen", lambda root: tmp_path)
    monkeypatch.setattr(backend, "FROZEN_HASHES", {})
    monkeypatch.setattr(backend, "_projection", lambda root, refs: ({key: {} for key in backend.STRATEGY_IDS}, {}, {}, []))

    def broken_snapshot(*args):
        raise backend.SelectedStrategyError("SOURCE_HASH_MISMATCH:current_snapshot")

    def forbidden_fallback(*args):
        pytest.fail("A corrupt current snapshot must block, not relabel an earlier signal")

    monkeypatch.setattr(backend, "_current_day", broken_snapshot)
    monkeypatch.setattr(backend, "_historical_day", forbidden_fallback)
    package = backend.build_package({"daily_root": tmp_path})
    for strategy in package["strategies"].values():
        assert strategy["application"]["status"] == "BLOCKED"
        assert strategy["application"]["rows"] == []
        assert "SOURCE_HASH_MISMATCH" in strategy["application"]["reason"]


def test_publish_cannot_overwrite_a_frozen_or_input_artifact(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    package = {"schema_version": 1, "selection_basis": backend.SELECTION_BASIS,
               "strategies": {name: {} for name in backend.STRATEGY_IDS}, "source_root": str(source)}
    with pytest.raises(backend.SelectedStrategyError, match="MUTATE_FROZEN_SOURCE"):
        backend.publish(package, source / "model.joblib")
    input_path = tmp_path / "feature.parquet"
    package["source_refs"] = {"features": {"path": str(input_path), "sha256": "0" * 64}}
    with pytest.raises(backend.SelectedStrategyError, match="MUTATE_INPUT_SOURCE"):
        backend.publish(package, input_path)


@pytest.mark.parametrize("change_report", [False, True])
def test_blocked_features_keep_only_the_hash_bound_requested_date(monkeypatch, tmp_path, change_report):
    monkeypatch.setattr(backend, "verify_frozen", lambda root: tmp_path)
    monkeypatch.setattr(backend, "FROZEN_HASHES", {})
    monkeypatch.setattr(backend, "_projection", lambda root, refs: ({key: {} for key in backend.STRATEGY_IDS}, {}, {}, []))
    feature = tmp_path / "features.parquet"
    feature.write_bytes(b"invalid snapshot bytes")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"status": "READY", "data_date": "2026-09-24",
        "model_id": "A2_HGB", "model_sha256": backend.A2_MODEL_SHA256,
        "selected_hgb_features": {"signal_date": "2026-09-24", "path": str(feature),
                                  "sha256": "0" * 64}}), encoding="utf-8")
    register = backend._register

    def checked_register(refs, key, path, expected=None):
        if key == "current/selected_hgb_features.parquet" and change_report:
            report.write_text(json.dumps({"data_date": "2026-09-25"}), encoding="utf-8")
        return register(refs, key, path, expected)

    def forbidden(*args, **kwargs):
        pytest.fail("An invalid current snapshot must not infer or use a historical signal")

    monkeypatch.setattr(backend, "_register", checked_register)
    monkeypatch.setattr(backend, "_historical_day", forbidden)
    monkeypatch.setattr(backend, "infer_targets", forbidden)
    monkeypatch.setattr(backend, "_infer_with_scores", forbidden)
    package = backend.build_package({"daily_root": tmp_path}, current_report_path=report)
    for item in package["strategies"].values():
        application = item["application"]
        assert application["status"] == "BLOCKED" and application["rows"] == []
        assert application["signal_date"] is None
        assert application["requested_signal_date"] == (None if change_report else "2026-09-24")
        assert "SOURCE_HASH_MISMATCH" in application["reason"]


def test_shared_scores_capture_the_single_prediction_pass_without_changing_public_ids(monkeypatch):
    import numpy as np
    runtime, calls = _runtime(), []

    class Model:
        def __init__(self, name):
            self.name = name

        def predict(self, frame):
            calls.append(self.name)
            assert list(frame) == list(backend.FEATURES)
            return np.ones(len(frame)) * .03

        def fit(self, *args, **kwargs):
            pytest.fail("Frozen inference must never train")

    class Optimizer:
        SPECS = {name: name for name in backend.STRATEGY_IDS}

        @staticmethod
        def solve(day, shares, values, nav, risk, strategy, signal):
            calls.append(strategy)
            assert len(day) == 40 and list(day.raw_rank) == list(range(1, 41))
            assert day.pred_hgb.eq(.03).all() and shares == values == {} and nav == 1
            return {"T1": .1}, {"solver_failed": False}

    runtime.update(model=Model("hgb_predict"), q10=Model("q10_predict"), optimizer=Optimizer(), risk={})
    monkeypatch.setattr(backend, "_runtime", lambda root: runtime)
    day = _day()
    day["security_id"] = [f"SEC-{rank}" for rank in range(1, 41)]
    day["future_return_label"] = 999
    day["execution_open"] = 999
    applications, snapshot = backend._infer_with_scores(day)
    assert calls == ["hgb_predict", "q10_predict", *backend.STRATEGY_IDS]
    assert set(applications) == set(backend.STRATEGY_IDS)
    assert snapshot["signal_date"] == snapshot["requested_signal_date"] == "2026-09-24"
    assert [row["ticker"] for row in snapshot["rows"]] == sorted(day.ticker)
    assert [row["hgb_rank"] for row in snapshot["rows"]] == list(range(1, 41))
    assert all(set(row) == {"ticker", "security_id", "raw_rank", "raw_score", "pred_hgb", "hgb_rank"}
               for row in snapshot["rows"])
    calls.clear()
    assert set(backend.infer_targets(day)) == set(backend.STRATEGY_IDS)
    assert calls == ["hgb_predict", "q10_predict", *backend.STRATEGY_IDS]


def test_daily_projection_keeps_recorded_cost_units_and_missing_flags_unknown():
    import pandas as pd
    ledger = pd.DataFrame([{"execution_date": pd.Timestamp("2026-01-05"), "nav": .9998,
        "cash_weight": .8, "net_return": -.0002, "gross_return": 0., "pretrade_nav": 1.,
        "turnover": .2, "transaction_cost_amount": .0002, "transaction_cost_fraction": .0002,
        "gross_exposure": .2, "actual_name_count": 2, "skipped_buy_count": 0, "blocked_sell_count": 0}])
    row = backend._daily_rows(ledger)[0]
    assert row["date"] == "2026-01-05" and row["transaction_cost_amount"] == .0002
    assert row["holding_count"] == 2 and row["skipped_buy_count"] == row["blocked_sell_count"] == 0
    assert row["stale_mark_count"] is row["blocked_rebalance_count"] is row["buy_cash_scale"] is None
    ledger["actual_name_count"] = 1.5
    with pytest.raises(backend.SelectedStrategyError, match="INVALID_RECORDED_COUNT"):
        backend._daily_rows(ledger)


def test_current_rank_join_preserves_and_checks_feature_security_identity(tmp_path):
    frame = _day().drop(columns=["raw_rank", "raw_score"])
    frame["security_id"] = [f"SEC-{rank}" for rank in range(1, 41)]
    snapshot = tmp_path / "current.parquet"
    frame.to_parquet(snapshot, index=False)
    report = tmp_path / "report.json"
    rows = [{"ticker": f"T{rank}", "security_id": f"SEC-{rank}", "rank": rank, "score": 41. - rank}
            for rank in range(1, 41)]
    payload = {"status": "READY", "data_date": "2026-09-24", "model_id": "A2_HGB",
        "model_sha256": backend.A2_MODEL_SHA256, "ranked_rows": rows,
        "selected_hgb_features": {"signal_date": "2026-09-24", "path": str(snapshot), "sha256": backend.digest(snapshot)}}
    report.write_text(json.dumps(payload), encoding="utf-8")
    joined, signal, note = backend._current_day({}, report, {})
    assert signal == "2026-09-24" and note == ""
    assert joined.security_id.tolist() == frame.security_id.tolist()
    assert joined.raw_rank.tolist() == list(range(1, 41))
    payload["ranked_rows"][0]["security_id"] = "OTHER_SECURITY"
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(backend.SelectedStrategyError, match="SECURITY_IDENTITY_MISMATCH"):
        backend._current_day({}, report, {})


def test_projection_refuses_a_changed_raw_reference_before_reading_ledgers(monkeypatch, tmp_path):
    relative = "audit_20260926/raw_daily.parquet"
    raw = tmp_path / relative
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"changed raw reference")
    monkeypatch.setattr(backend, "REPLAY_HASHES", {relative: "0" * 64})
    import pandas as pd
    monkeypatch.setattr(pd, "read_parquet", lambda *args, **kwargs: pytest.fail("Hash rejection must precede source reads"))
    with pytest.raises(backend.SelectedStrategyError, match="SOURCE_HASH_MISMATCH"):
        backend._projection(tmp_path, {})


def test_score_projection_rejects_missing_security_identity_and_incomplete_scope():
    day = _day()
    day["pred_hgb"] = .02
    day["security_id"] = [f"SEC-{rank}" for rank in range(1, 41)]
    with pytest.raises(backend.SelectedStrategyError, match="REQUIRE_RAW_TOP40"):
        backend._score_rows(day.iloc[:20])
    day.loc[0, "security_id"] = None
    with pytest.raises(backend.SelectedStrategyError, match="SECURITY_IDENTITY"):
        backend._score_rows(day)


@pytest.fixture
def frozen_synthetic_optimizer():
    """Execute only the current retained solve definition; never load artifacts."""
    import ast
    from types import SimpleNamespace
    import numpy as np
    import pandas as pd
    from scipy.optimize import minimize
    # MODULE_PATH is .../scripts/research/a2/portfolio/selected_hgb.py.
    path = MODULE_PATH.parent.parent / "retained/a2_top20_all_methods_20260925/optimize_route.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"SPECS", "COST_ONE_WAY", "MAX_WEIGHT", "MAX_GROSS", "ZERO_CUTOFF"}):
            constants[node.targets[0].id] = ast.literal_eval(node.value)
    def covariance_for(bundle, signal, names):
        indices = [bundle["tickers"].index(ticker) for ticker in names]
        return bundle["covariance"][np.ix_(indices, indices)].copy()
    namespace = {"np": np, "pd": pd, "minimize": minimize,
                 "risk_aux": SimpleNamespace(covariance_for=covariance_for), **constants}
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "solve")
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return SimpleNamespace(solve=namespace["solve"], **constants)


def _direct_policy_inputs():
    import numpy as np
    import pandas as pd
    names = [f"T{rank:02d}" for rank in range(1, 41)]
    day = pd.DataFrame({"ticker": names, "raw_rank": range(1, 41),
        "pred_hgb": np.arange(1, 41) / 1000., "pred_q10": -.1,
        "raw_rank_strength": 1. - np.arange(40) / 39.})
    bundle = {"tickers": names, "covariance": np.eye(40) * .001}
    return day, bundle, pd.Timestamp("2026-09-24")


def test_direct_policy_hgb_top20_controls_new_buys_without_mutating_input(frozen_synthetic_optimizer):
    import pandas as pd
    day, bundle, signal = _direct_policy_inputs()
    original = day.copy(deep=True)
    target, diagnostic = backend.solve_targets(day, {}, {}, 1., bundle,
        frozen_synthetic_optimizer.SPECS["HGB_DIAG_5"], signal,
        optimizer=frozen_synthetic_optimizer, policy=backend.DIRECT_POLICY)
    assert not diagnostic["solver_failed"]
    assert target["T40"] > 0 and "T01" not in target
    assert set(target) <= {f"T{rank:02d}" for rank in range(21, 41)}
    pd.testing.assert_frame_equal(day, original)


def test_direct_policy_old_hgb_candidates_can_sell_but_cannot_increase(frozen_synthetic_optimizer):
    day, bundle, signal = _direct_policy_inputs()
    # Same Top20 in both policies; the low-risk old name would otherwise grow.
    day["pred_hgb"] = .005
    day.loc[39, "pred_hgb"] = .004
    bundle["covariance"][39, 39] = .00001
    old = {"T40": .01}
    target, diagnostic = backend.solve_targets(day, {"T40": 1.}, old, 1., bundle,
        frozen_synthetic_optimizer.SPECS["HGB_DIAG_5"], signal,
        optimizer=frozen_synthetic_optimizer, policy=backend.DIRECT_POLICY)
    assert not diagnostic["solver_failed"]
    assert target.get("T40", 0.) <= old["T40"] + 1e-8
    legacy, diagnostic = frozen_synthetic_optimizer.solve(day, {"T40": 1.}, old, 1.,
        bundle, frozen_synthetic_optimizer.SPECS["HGB_DIAG_5"], signal)
    assert not diagnostic["solver_failed"] and legacy["T40"] > old["T40"] + .001


def test_legacy_policy_reuses_original_output_and_globals(frozen_synthetic_optimizer):
    day, bundle, signal = _direct_policy_inputs()
    spec = frozen_synthetic_optimizer.SPECS["HGB_DIAG_5"]
    original_minimize = frozen_synthetic_optimizer.solve.__globals__["minimize"]
    expected = frozen_synthetic_optimizer.solve(day, {}, {}, 1., bundle, spec, signal)
    actual = backend.solve_targets(day, {}, {}, 1., bundle, spec, signal,
                                   optimizer=frozen_synthetic_optimizer)
    assert actual == expected
    backend.solve_targets(day, {}, {}, 1., bundle, spec, signal,
        optimizer=frozen_synthetic_optimizer, policy=backend.DIRECT_POLICY)
    assert frozen_synthetic_optimizer.solve.__globals__["minimize"] is original_minimize


def test_direct_policy_retains_risk_weighting_and_cash(frozen_synthetic_optimizer):
    import numpy as np
    day, bundle, signal = _direct_policy_inputs()
    day["pred_hgb"] = .005
    bundle["covariance"] = np.full((40, 40), .0009) + np.eye(40) * .0001
    targets = {}
    for strategy in backend.STRATEGY_IDS:
        target, diagnostic = backend.solve_targets(day, {}, {}, 1., bundle,
            frozen_synthetic_optimizer.SPECS[strategy], signal,
            optimizer=frozen_synthetic_optimizer, policy=backend.DIRECT_POLICY)
        assert not diagnostic["solver_failed"]
        assert all(0 <= weight <= .1 + 1e-7 for weight in target.values())
        targets[strategy] = target
    assert sum(targets["HGB_FACTOR_5"].values()) < sum(targets["HGB_DIAG_5"].values()) - .5
    assert 0 < sum(targets["HGB_FACTOR_5"].values()) < .2
    # Stable ticker ordering resolves equal HGB scores for both risk variants.
    assert set(targets["HGB_DIAG_5"]) == {f"T{rank:02d}" for rank in range(1, 21)}


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), -float("inf"), "invalid"])
def test_direct_policy_rejects_nonfinite_predictions(frozen_synthetic_optimizer, bad_score):
    day, bundle, signal = _direct_policy_inputs()
    day["pred_hgb"] = day.pred_hgb.astype(object)
    day.loc[0, "pred_hgb"] = bad_score
    with pytest.raises(backend.SelectedStrategyError, match="FINITE_SCORES"):
        backend.solve_targets(day, {}, {}, 1., bundle,
            frozen_synthetic_optimizer.SPECS["HGB_DIAG_5"], signal,
            optimizer=frozen_synthetic_optimizer, policy=backend.DIRECT_POLICY)


def _policy_storage_paths(tmp_path):
    """Keep all synthetic roots distinct even when pytest temp is in real cache."""
    names = {"repo_root": "repo", "data_root": "data", "cache_root": "cache",
             "daily_root": "daily", "backtest_root": "backtests", "results_root": "results",
             "envs_root": "envs"}
    paths = {key: tmp_path / name for key, name in names.items()}
    config = paths["repo_root"] / "config/storage_paths.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({key: str(value) for key, value in paths.items()}), encoding="utf-8")
    return paths


@pytest.mark.parametrize("policy, relative", [
    (backend.LEGACY_POLICY, "A2_selected_hgb/latest.json"),
    (backend.DIRECT_POLICY, "A2_selected_hgb/direct_hgb_r1/latest.json"),
])
def test_active_policy_resolves_separate_daily_package(tmp_path, policy, relative):
    paths = _policy_storage_paths(tmp_path)
    repo, daily = paths["repo_root"], paths["daily_root"]
    config = repo / "config/research_governance/selected_hgb_policy.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"schema_version": 1, "policy_id": policy,
                                  "package_relative_path": relative}), encoding="utf-8")
    assert backend.active_policy(paths) == (policy, (daily / relative).resolve())


def test_active_policy_missing_config_preserves_legacy_and_invalid_path_is_rejected(tmp_path):
    paths = _policy_storage_paths(tmp_path)
    repo, daily = paths["repo_root"], paths["daily_root"]
    assert backend.active_policy(paths) == (backend.LEGACY_POLICY, (daily / "A2_selected_hgb/latest.json").resolve())
    config = repo / "config/research_governance/selected_hgb_policy.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"schema_version": 1, "policy_id": backend.DIRECT_POLICY,
                                  "package_relative_path": "../outside.json"}), encoding="utf-8")
    with pytest.raises(backend.SelectedStrategyError, match="CONFIG_INVALID"):
        backend.active_policy(paths)



def test_direct_inference_both_risks_use_the_shared_hgb_scores(monkeypatch, frozen_synthetic_optimizer):
    import numpy as np
    day = _day()
    runtime = _runtime()
    class MeanModel:
        def predict(self, frame):
            return np.arange(1, 41) / 1000.
    class DownsideModel:
        def predict(self, frame):
            return np.full(40, -.1)
    runtime.update(model=MeanModel(), q10=DownsideModel(), optimizer=frozen_synthetic_optimizer,
                   risk={"tickers": day.ticker.tolist(), "covariance": np.eye(40) * .001})
    monkeypatch.setattr(backend, "_runtime", lambda root: runtime)
    applications, scores = backend._infer_with_scores(day, policy=backend.DIRECT_POLICY)
    eligible = {row["ticker"] for row in scores["rows"][:20]}
    assert eligible == {f"T{rank}" for rank in range(21, 41)}
    for application in applications.values():
        assert application["policy_id"] == backend.DIRECT_POLICY
        assert application["eligibility_basis"] == "HGB_TOP20_PRED_HGB_DESC_TICKER_ASC"
        assert {row["ticker"] for row in application["rows"] if row["target_weight"] > 0} <= eligible
        assert application["model_fit_calls"] == 0



def test_direct_build_package_uses_manifest_ledgers_without_legacy_projection(monkeypatch, tmp_path):
    from copy import deepcopy
    from scripts.research.a2.evaluation.three_strategy_extension import reference
    monkeypatch.setattr(backend, "verify_frozen", lambda root: tmp_path)
    monkeypatch.setattr(backend, "FROZEN_HASHES", {})
    monkeypatch.setattr(backend, "_projection", lambda *args: pytest.fail("Direct package cannot read legacy ledgers"))
    monkeypatch.setattr(backend, "_historical_day", lambda *args: pytest.fail("Current synthetic input must be used"))
    monkeypatch.setattr(backend, "_merge_archived_snapshots", lambda *args, **kwargs: None)
    period = {"start": "2026-09-24", "end": "2026-09-25", "days": 2,
              "price_basis": "PIT_FORWARD_REHAB_INDEX", "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"}
    strategies = {}
    for sid, nav in (("RAW_A2", 1.02), ("HGB_DIAG_5", 1.2), ("HGB_FACTOR_5", 1.05)):
        daily_path, target_path = tmp_path / (sid + "_daily.parquet"), tmp_path / (sid + "_targets.parquet")
        daily_path.write_bytes(("synthetic daily " + sid).encode())
        target_path.write_bytes(("synthetic targets " + sid).encode())
        daily = [{"date": period["start"], "nav": 1., "net_return": 0., "cash_weight": .9},
                 {"date": period["end"], "nav": nav, "net_return": nav - 1., "cash_weight": .9}]
        targets = [{"signal_date": "2026-09-24", "rows": [{"ticker": "T40", "target_weight": .1,
                    "weight_before": 0., "action": "BUY"}]}]
        strategies[sid] = {"label": sid, "daily": daily, "targets": targets,
            "summary": {"end_nav": nav, "cumulative_return": nav - 1., "max_drawdown": 0.,
                        "turnover": .1, "mean_cash": .9, "days": 2},
            "outputs": {"daily": reference(daily_path), "targets": reference(target_path)}}
    historical = [{"signal_date": "2026-09-24", "ticker": "T40", "pred_hgb": .03}]
    manifest = {"schema_version": 1, "source_id": "NEW_PIT_COMPARISON", "status": "READY",
        "policy_id": backend.DIRECT_POLICY, "model_fit_calls": 0, "broker_action_allowed": False,
        "performance_period": period, "strategies": strategies, "shared_scores_historical": historical,
        "source_refs": [], "requested_end_date": "2026-09-25", "blocked_next": None,
        "cost_one_way": .0005, "initial_cash_coordinate": 1., "limitations": ["synthetic direct replay"]}
    manifest_path = tmp_path / "direct_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    current = _day()
    monkeypatch.setattr(backend, "_current_day", lambda *args: (current, "2026-09-24", ""))
    calls = []
    def inference(day, state=None, *, source_root=None, policy=backend.LEGACY_POLICY):
        calls.append(policy)
        applications = {sid: {"status": "READY", "signal_date": "2026-09-24", "rows": [],
            "target_cash_weight": 1., "policy_id": policy} for sid in backend.STRATEGY_IDS}
        return applications, {"status": "READY", "signal_date": "2026-09-24", "rows": [], "reason": ""}
    monkeypatch.setattr(backend, "_infer_with_scores", inference)
    package = backend.build_package({"daily_root": tmp_path}, policy=backend.DIRECT_POLICY,
                                     replay_manifest=manifest_path)
    assert calls == [backend.DIRECT_POLICY]
    assert package["policy_id"] == backend.DIRECT_POLICY
    assert package["performance_period"] == period
    assert package["shared_scores"]["historical"] == historical
    assert package["performance_extension"]["manifest"] == reference(manifest_path)
    for sid in backend.STRATEGY_IDS:
        for field in ("daily", "targets", "summary"):
            assert package["strategies"][sid][field] == manifest["strategies"][sid][field]
        assert package["strategies"][sid]["application"]["policy_id"] == backend.DIRECT_POLICY
    assert package["raw_reference"]["daily"] == strategies["RAW_A2"]["daily"]
    # All returned performance fields are detached from the stored manifest data.
    old_manifest = deepcopy(manifest)
    package["strategies"]["HGB_DIAG_5"]["daily"][0]["nav"] = 999.
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == old_manifest
