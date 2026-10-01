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
