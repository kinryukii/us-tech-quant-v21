"""Synthetic integration only: never invoke the real-input entrypoint."""
import json

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.factors import economic_return_features as features
from scripts.research.a2.factors import economic_return_targets as targets
from scripts.research.a2.factors import economic_return_preflight as runner


def fixture():
    calendar = pd.bdate_range("2020-01-02", periods=400)
    raw = pd.DataFrame([(d, ticker, 100.) for d in calendar for ticker in ("AAA", "BBB", "QQQ")],
                       columns=["trade_date", "ticker", "close"])
    panel = pd.DataFrame([(d, ticker) for d in calendar[200:220] for ticker in ("AAA", "BBB")],
                         columns=["signal_date", "ticker"])
    maturity = pd.Series(calendar, index=calendar).shift(-20)
    panel["target_end_date"] = panel.signal_date.map(maturity)
    events = pd.DataFrame(columns=["code", "ex_div_date", *features.ACTION_FIELDS])
    bindings = {"equities": [{"ticker": t, "moomoo_transport_code": "US." + t} for t in ("AAA", "BBB")],
                "QQQ": {"ticker": "QQQ", "moomoo_transport_code": "US.QQQ"},
                "rehab": {"path": "synthetic-events", "sha256": "synthetic-event-hash"}}
    contract = {"cohort": {"rows": len(panel), "dates": 20, "names_per_date": 2,
        "first_date": str(calendar[200].date()), "last_date": str(calendar[219].date()),
        "key_sha256": runner.key_fingerprint(panel)}, "action_schema_basis": runner.ARCHIVE_SCHEMA,
        "event_identity_conditioning": runner.TRANSPORT_CONDITION,
        "event_query_scope": runner.QUERY_SCOPE, "start_inclusive": "2020-01-01",
        "rehab_status": {"path": "synthetic-status", "sha256": "synthetic-status-hash"},
        "sdk_schema": {"path": "synthetic-schema", "sha256": "synthetic-schema-hash"}}
    query = pd.DataFrame({"code": ["US.AAA", "US.BBB", "US.QQQ"], "status": "PASS", "row_count": 0})
    return raw, events, panel, calendar, bindings, query, contract


def stage(parts):
    return runner.stage_coverage(*parts, features, targets)


def test_stage_preserves_keys_never_ranks_and_separates_identity(monkeypatch):
    parts = fixture()
    monkeypatch.setattr(pd.Series, "rank", lambda *a, **k: pytest.fail("rank called"))
    out, summary = stage(parts)
    pd.testing.assert_frame_equal(out[["signal_date", "ticker"]], parts[2][["signal_date", "ticker"]])
    assert out.transport_target_valid.all()
    assert not out.strict_target_valid.any() and summary["strict_valid_label_rows"] == 0
    assert out.delay_potential_window_support.all() and out.max_potential_month_support.all()
    assert summary["model_admission"] == "BLOCKED" and summary["fits_added"] == 0
    assert not {"close", "prior_close", "daily_gross_return", "target", "price_delay_d1", "max_daily_return"} & set(out)
    assert all(f"economic_stock_return_{h}d" not in out for h in targets.HORIZONS)


def test_cash_without_unit_evidence_is_unknown_and_future_keys_are_retained():
    parts = list(fixture())
    row = dict.fromkeys(features.ACTION_FIELDS, np.nan)
    row.update(code="US.AAA", ex_div_date=parts[3][215], per_cash_div=1.)
    parts[1] = pd.DataFrame([row])
    parts[5].loc[parts[5].code.eq("US.AAA"), "row_count"] = 1
    out, summary = stage(parts)
    assert summary["event_status_counts"] == {"UNCONFIRMED_CASH_UNIT": 1}
    assert len(out) == len(parts[2]) and out.transport_target_valid.sum() < len(out)
    assert not out.loc[out.signal_date.lt(parts[3][215]), "transport_target_universe_complete"].any()
    assert out.loc[out.signal_date.ge(parts[3][215]), "transport_target_universe_complete"].all()


def test_split_is_only_conditionally_computable_and_failed_query_never_means_no_event():
    parts = list(fixture())
    row = dict.fromkeys(features.ACTION_FIELDS, np.nan)
    row.update(code="US.AAA", ex_div_date=parts[3][215], split_ratio=.5, split_base=1., split_ert=2.)
    parts[1] = pd.DataFrame([row])
    parts[5].loc[parts[5].code.eq("US.AAA"), "row_count"] = 1
    parts[0].loc[parts[0].ticker.eq("AAA") & parts[0].trade_date.ge(parts[3][215]), "close"] = 50.
    out, summary = stage(parts)
    assert summary["event_status_counts"] == {"SUPPORTED": 1}
    assert out.transport_target_valid.all() and not out.strict_target_valid.any()
    parts[5].loc[parts[5].code.eq("US.BBB"), "status"] = "FAIL"
    failed, summary = stage(parts)
    assert not failed.loc[failed.ticker.eq("BBB"), "transport_target_valid"].any()
    assert summary["daily_return_status_counts"]["EVENT_COVERAGE_UNCONFIRMED"] == 400


def test_partial_archive_schema_and_unconfirmed_identity_are_not_promoted():
    parts = list(fixture())
    row = dict.fromkeys(features.ACTION_FIELDS, np.nan)
    row.update(code="US.AAA", ex_div_date=parts[3][215], split_ratio=.5)
    parts[1] = pd.DataFrame([row]).drop(columns="special_dividend")
    parts[5].loc[parts[5].code.eq("US.AAA"), "row_count"] = 1
    _, summary = stage(parts)
    assert not summary["evidence"]["archive_action_columns_complete"]
    assert summary["event_status_counts"] == {"INCOMPLETE_ACTION_EVIDENCE": 1}
    parts[1]["special_dividend"] = np.nan
    parts[6]["event_identity_conditioning"] = "UNCONFIRMED"
    _, summary = stage(parts)
    assert summary["event_status_counts"] == {"UNKNOWN_SECURITY_IDENTITY": 1}


def test_whole_date_deletion_and_key_substitution_fail_fixed_cohort():
    parts = fixture()
    panel, expected = parts[2], parts[6]["cohort"]
    with pytest.raises(RuntimeError, match="FROZEN_COHORT"):
        runner.validate_cohort(panel.iloc[2:], expected)
    wrong = panel.copy()
    wrong.loc[0, "ticker"] = "REPLACEMENT"
    with pytest.raises(RuntimeError, match="FROZEN_COHORT"):
        runner.validate_cohort(wrong, expected)
    assert runner.key_fingerprint(panel.iloc[::-1]) == expected["key_sha256"]


def test_unfrozen_contract_fails_before_any_import_or_body(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"phase": "MODEL", "cohort": {}}))
    monkeypatch.setattr(runner.importlib.util, "spec_from_file_location", lambda *a, **k: pytest.fail("import before freeze"))
    with pytest.raises(RuntimeError, match="COVERAGE_CONTRACT_NOT_FROZEN"):
        runner.frozen_setup(contract, tmp_path / "nonexistent-bindings.json")
