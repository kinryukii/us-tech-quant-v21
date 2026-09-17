"""Synthetic fixed-horizon coverage and weight invariants."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.options import cli, coverage as c, input_adapter as old
from scripts.research.a2.options.contracts import Invalid, calendar
from tests.research.a2.options.test_expression_pilot import external_tmp_path


def fixture(day="2025-03-07"):
    date = pd.Timestamp(day)
    entry = calendar().sessions.get_loc(date) + 1
    panel = pd.DataFrame([{"decision_id": day+":UID", "signal_date": date, "underlying_uid": "UID",
                           "ticker": "T", "input_reason": "OK", "planned_entry": calendar().schedule.iloc[entry]["open"].isoformat()}])
    keys = c.expected_price_keys(panel)
    marks = keys.copy()
    marks["price"] = 100. + np.arange(len(keys))
    marks["valid"] = True
    marks["identity_status"] = "VERIFIED"
    marks["action_status"] = "UNCHANGED"
    marks["lifecycle_status"] = "RESOLVED"
    marks["source"] = "FIXTURE_SAME_SOURCE"
    marks["price_kind"] = "SYNTHETIC_OPEN"
    return panel, keys, marks


def test_future_holdings_and_ranks_cannot_change_expected_keys_or_labels():
    p, k, m = fixture()
    base = c.market_labels(p, m)
    p["future_holdings"] = 0
    p["future_rank"] = 999
    pd.testing.assert_frame_equal(k, c.expected_price_keys(p))
    pd.testing.assert_frame_equal(base, c.market_labels(p, m))


def test_sold_second_session_independent_prices_still_label_both_horizons():
    p, _, m = fixture()
    positions = m.iloc[:2].rename(columns={"session": "date", "price": "current_price"})
    positions["mark_source_date"] = positions.date
    positions["stale_mark"] = False
    members = m.rename(columns={"session": "signal_date", "underlying_uid": "cusip"})
    before, _ = old.daily_labels(p, positions, members)
    assert before.status.eq("MISSING").all()
    after = c.market_labels(p, m)
    assert after.path_valid.all()
    assert after.absolute_return.tolist() == pytest.approx([.05, .20])


def test_sparse_fifth_row_not_fifth_trading_session_endpoint():
    p, _, m = fixture()
    m.loc[5, ["price", "valid"]] = [np.nan, False]
    labels = c.market_labels(p, m)
    assert not labels.endpoint_valid.iloc[0]
    assert pd.isna(labels.endpoint_return.iloc[0])
    assert labels.endpoint_valid.iloc[1] and not labels.path_valid.iloc[1]


def test_endpoints_with_missing_middle_allow_only_endpoint_when_lifecycle_independently_resolved():
    p, _, m = fixture()
    m.loc[2, ["price", "valid"]] = [np.nan, False]
    labels = c.market_labels(p, m)
    assert labels.endpoint_valid.all() and not labels.path_valid.any()
    assert labels.endpoint_return.tolist() == pytest.approx([.05, .20])
    assert labels[["absolute_return", "mfe", "mae", "realized_volatility"]].isna().all().all()


def test_cutoff_independent_horizons_and_no_post2025_keys():
    p, k, m = fixture("2025-12-12")
    assert k.session.lt("2026-01-01").all()
    labels = c.market_labels(p, m)
    assert labels.path_valid.iloc[0]
    assert labels.cutoff_censored.iloc[1] and labels.fixed_weight.iloc[1] == 0


def test_unknown_original_uid_stays_in_population_without_rank21_replacement():
    p, _, m = fixture()
    p.loc[0, "input_reason"] = "HISTORICAL_UID_OR_ELIGIBILITY_UNVERIFIED"
    labels = c.market_labels(p, m)
    assert len(labels) == 2 and not labels.endpoint_valid.any()
    assert labels.fixed_weight.eq(1).all()


def test_no_secondary_source_splice():
    p, _, m = fixture()
    m.loc[20, "source"] = "SECONDARY"
    with pytest.raises(Invalid, match="SOURCE_SPLICE"):
        c.market_labels(p, m)


def test_adjusted_price_index_no_second_dividend_addition():
    p, _, m = fixture()
    m["price"] = 100.
    m["cash_dividend"] = 20.
    m["split_ratio"] = 2.
    labels = c.market_labels(p, m)
    assert labels.absolute_return.eq(0).all()


def weighted_fixture():
    return pd.DataFrame({"decision_id": ["a", "b", "c", "d"],
                         "signal_date": pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-03", "2025-01-06"]),
                         "cutoff_censored": [False, False, False, False],
                         "seen": [True, False, True, False], "ret": [.2, np.nan, -.1, np.nan]})


def test_fixed_weights_include_differing_missingness_and_wholly_missing_date():
    g = weighted_fixture()
    assert c.fixed_weights(g).tolist() == pytest.approx([1/6, 1/6, 1/3, 1/3])
    result = c.sensitivity(g, "seen", "ret")
    assert result["A"] == pytest.approx(0)
    assert result["q"] == pytest.approx(.5)
    assert result["x_star"] == pytest.approx(0)
    assert g[g.seen].groupby("signal_date").ret.mean().mean() == pytest.approx(.05)


@pytest.mark.parametrize("all_seen", [False, True])
def test_q_zero_and_q_one_are_explicit(all_seen):
    g = weighted_fixture()
    g["seen"] = all_seen
    g["ret"] = .1 if all_seen else np.nan
    result = c.sensitivity(g, "seen", "ret")
    if all_seen:
        assert result["q"] == 0 and result["A"] == pytest.approx(.1) and result["x_star"] is None
    else:
        assert result["q"] == pytest.approx(1) and result["A"] == 0 and result["x_star"] == 0
        assert result["observed_weight_renormalized_mean"] is None
    json.dumps(result, allow_nan=False)


def test_reordered_inputs_produce_identical_fixed_tables():
    p, keys, marks = fixture()
    pd.testing.assert_frame_equal(c.expected_price_keys(p.sample(frac=1)), keys)
    pd.testing.assert_frame_equal(c.market_labels(p, marks), c.market_labels(p, marks.sample(frac=1, random_state=7)))


def test_real_user_cli_dispatches_independent_adapter_path(monkeypatch):
    called = []
    def fake(*a, **kw):
        called.append((a, kw))
        return dict(run_identity="fixture", scope="FULL_FROZEN_RANGE", stock_path_research_status="COMPLETE",
                    required_stage_success=True, opportunity_rows=15000)
    monkeypatch.setattr(c, "run_coverage", fake)
    assert cli.main(["--mode", "real-stock", "--coverage"]) == 0
    assert len(called) == 1


def test_actual_cli_rejects_unbound_path_before_any_open(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("no input bytes permitted")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    assert cli.main(["--mode", "real-stock", "--coverage", "--input", "unbound2026.parquet"]) == 2
    assert cli.main(["--mode", "real-stock", "--coverage", "--config", "unbound.json"]) == 2


def test_invalid_economic_date_and_duplicate_price_fail_closed():
    p, _, m = fixture()
    with pytest.raises(Invalid, match="DUPLICATE_INDEPENDENT"):
        c.market_labels(p, pd.concat([m, m.iloc[:1]]))
    m.loc[0, "session"] = pd.Timestamp("2026-01-02")
    with pytest.raises(Invalid, match="NON_PRE2026_PRICE"):
        c.market_labels(p, m)


def test_isolated_interruption_resume_preserves_completed_partition(monkeypatch, external_tmp_path):
    import hashlib
    from types import SimpleNamespace
    from scripts.research.a2.options import independent_prices, historical_quotes
    tmp_path = external_tmp_path
    panel, _, marks = fixture()
    positions = marks.rename(columns={"session": "date", "price": "current_price"}).copy()
    positions["mark_source_date"] = positions.date
    positions["stale_mark"] = False
    members = marks.rename(columns={"session": "signal_date", "underlying_uid": "cusip"})
    labels, _ = old.daily_labels(panel, positions, members)
    root = tmp_path / c.TEMPLATE / "overnight" / c.RUN_ID
    root.mkdir(parents=True)
    cfg = root / "run_config.json"
    cfg.write_text(json.dumps({"overnight_task": "SYNTHETIC_ENGINEERING_INTERRUPTION"}))
    prior = tmp_path / c.TEMPLATE / "continuation/run/full_final/real_stock_path_labels.csv"
    prior.parent.mkdir(parents=True)
    labels.to_csv(prior, index=False)
    monkeypatch.setattr(c, "CONFIG_SHA", hashlib.sha256(cfg.read_bytes()).hexdigest())
    monkeypatch.setattr(c, "OLD_LABEL_SHA", hashlib.sha256(prior.read_bytes()).hexdigest())
    monkeypatch.setattr(c, "resolve", lambda: SimpleNamespace(results_root=tmp_path))
    monkeypatch.setattr(old, "load_bound_inputs", lambda: ({"a2_positions": positions, "daily_u_membership": members}, [], []))
    monkeypatch.setattr(old, "opportunity_panel", lambda *a: panel)
    def interrupted(*args):
        raise RuntimeError("SYNTHETIC_INTERRUPTION_AFTER_SAVED_PARTITION")
    monkeypatch.setattr(independent_prices, "load_independent_prices", interrupted)
    with pytest.raises(RuntimeError, match="SYNTHETIC_INTERRUPTION"):
        c.run_coverage(root / "run", cfg)
    saved = json.loads((root / "run/run_manifest.json").read_text())
    assert saved["completed_stages"] == ["original_reproduced"]
    old_hash = saved["artifact_sha256"]["original_strict_labels.csv"]
    def price_stub(keys, panel, output):
        output.mkdir(parents=True, exist_ok=True)
        return marks, {"domain": "SYNTHETIC"}
    monkeypatch.setattr(independent_prices, "load_independent_prices", price_stub)
    def qualification_stub(panel, output):
        output.mkdir(parents=True, exist_ok=True)
        for name in c.OPTION_ARTIFACTS:
            (output / name).write_text("SYNTHETIC_ZERO_HTTP")
        return {"economic_http_requests": 0}
    monkeypatch.setattr(historical_quotes, "write_qualification", qualification_stub)
    def no_repeat(*a, **kw):
        raise AssertionError("completed original partition must not rerun")
    monkeypatch.setattr(old, "daily_labels", no_repeat)
    resumed = c.run_coverage(root / "run", cfg)
    assert resumed["completed_stages"][-1] == "finished"
    assert resumed["artifact_sha256"]["original_strict_labels.csv"] == old_hash
    assert resumed["opportunity_rows"] == 1 and not resumed["required_stage_success"]
    monkeypatch.setattr(old, "load_bound_inputs", no_repeat)
    assert c.run_coverage(root / "run", cfg) == resumed
    assert "historical_quotes.py" in resumed["code_sha256"]
    real_read_bytes = Path.read_bytes
    def changed_quote_code(path):
        value = real_read_bytes(path)
        return value + b"\n# changed fixture identity" if path.name == "historical_quotes.py" else value
    monkeypatch.setattr(Path, "read_bytes", changed_quote_code)
    with pytest.raises(Invalid, match="OUTPUT_IDENTITY_CHANGED"):
        c.run_coverage(root / "run", cfg)
    monkeypatch.setattr(Path, "read_bytes", real_read_bytes)
    (root / "run/option_evidence/actual_pairs.csv").write_text("SYNTHETIC_CHANGED")
    with pytest.raises(Invalid, match="OPTION_EVIDENCE_CHANGED:actual_pairs.csv"):
        c.run_coverage(root / "run", cfg)
