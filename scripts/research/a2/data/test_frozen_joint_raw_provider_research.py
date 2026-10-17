"""Synthetic in-memory provider checks; no real input files or account runs."""
import builtins

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.data.frozen_joint_raw_provider_research import (
    FrozenJointRawProviderResearch as Provider, RawProviderFailure,
)

DATES = ("2023-01-03", "2023-01-04")
TICKERS = ("AAA", "BBB")


def ref(letter, name):
    return dict(path="synthetic://" + name, sha256=letter * 64)


def held(day=DATES[0], ticker="BBB", **changes):
    return dict(signal_date=day, ticker=ticker, a2_prediction=.123456789012345,
                raw_uncertainty=.234567890123456, source_fit_cutoff="2023-01-01",
                source_kind="ORIGINAL_FROZEN_RAW_HELD", feature_source="EXACT_ORIGINAL_ROW",
                row_identity=42, **changes)


def args(**changes):
    values = dict(dates=DATES, tickers=TICKERS,
                  base_keys=[dict(signal_date=d, ticker="AAA", row_identity=i)
                             for i, d in enumerate(DATES)],
                  mu=np.array([[.7, 999.], [.8, 888.]]),
                  sigma=np.array([[0., 999.], [.03, 888.]]),
                  base_ref=ref("a", "base"), cache_ref=ref("b", "cache"),
                  held_rows=[held()], held_refs={2023: ref("c", "held2023")})
    values.update(changes)
    return values


def failure(call, reason, key=None):
    with pytest.raises(RawProviderFailure) as caught:
        call()
    error = caught.value
    assert error.reason == reason
    assert error.receipt["reason"] == reason
    if key is not None:
        assert error.key == key
        assert (error.receipt["signal_date"], error.receipt["ticker"]) == key
    return error


def test_exact_base_and_held_original_values_and_physical_provenance():
    p = Provider(**args())
    result = p.for_day(DATES[0], np.array([True, True]), tickers=TICKERS)
    np.testing.assert_array_equal(result.mu, [.7, .123456789012345])
    np.testing.assert_array_equal(result.sigma, [0., .234567890123456])
    base, supplement = result.provenance
    assert base["base_present"] is True and supplement["base_present"] is False
    assert base["exact_row_identity"] == {"physical_row_identity": 0}
    assert base["value_cell_identity"] == {"evaluation_date_index": 0,
                                            "original_cache_date_index": 0, "column": 0}
    assert supplement["exact_row_identity"] == {"physical_row_identity": 42}
    assert supplement["source_fit_cutoff"] == "2023-01-01"
    assert base["row_token"] != supplement["row_token"]
    for row in result.provenance:
        assert not any(row[k] for k in ("legal_identity_authority", "strict_PIT",
                                      "production_qualified", "certified_NAV"))
    assert not result.mu.flags.writeable and not result.sigma.flags.writeable


def test_original_nan_presence_cannot_be_replaced_by_finite_held_value():
    config = args()
    config["base_keys"].append(dict(signal_date=DATES[0], ticker="BBB", row_identity=100))
    config["mu"][0, 1] = np.nan
    error = failure(lambda: Provider(**config), "BASE_HELD_KEY_OVERLAP", (DATES[0], "BBB"))
    assert error.receipt["base_present"] is True
    assert "conflicting_source_ref" in error.receipt
    config["held_rows"] = []
    p = Provider(**config)
    failure(lambda: p.for_day(DATES[0], np.array([False, True])),
            "NONFINITE_OR_NEGATIVE_ORIGINAL_REQUIRED_VALUE", (DATES[0], "BBB"))


def test_full_cache_cell_is_not_row_presence_and_no_adjacent_day_fallback():
    p = Provider(**args())
    error = failure(lambda: p.for_day(DATES[1], np.array([False, True])),
                    "EXACT_REQUIRED_RAW_ROW_MISSING", (DATES[1], "BBB"))
    assert error.receipt["base_present"] is False
    assert len(error.receipt["consulted_source_refs"]) == 2


def test_nonrequired_and_reserved_nonmodeled_held_do_not_expand_score_demand():
    p = Provider(**args(held_rows=[]))
    result = p.for_day(DATES[1], np.array([True, False]))
    assert result.mu[0] == .8 and np.isnan(result.mu[1])
    assert len(result.provenance) == 1
    # The runner decides demand: a reserved/nonmodeled held name is still False.
    all_reserved = p.for_day(DATES[1], np.array([False, False]))
    assert np.isnan(all_reserved.mu).all() and all_reserved.provenance == ()
    # Once the original consumer actually requires that row, the same key fails.
    failure(lambda: p.for_day(DATES[1], np.array([True, True])),
            "EXACT_REQUIRED_RAW_ROW_MISSING", (DATES[1], "BBB"))


@pytest.mark.parametrize("field,value", [("a2_prediction", np.nan),
    ("a2_prediction", np.inf), ("raw_uncertainty", np.nan),
    ("raw_uncertainty", np.inf), ("raw_uncertainty", -.01)])
def test_invalid_required_original_values_fail_only_when_consumed(field, value):
    row = held()
    row[field] = value
    p = Provider(**args(held_rows=[row]))
    assert p.for_day(DATES[0], np.array([True, False])).mu[0] == .7
    failure(lambda: p.for_day(DATES[0], np.array([False, True])),
            "NONFINITE_OR_NEGATIVE_ORIGINAL_REQUIRED_VALUE", (DATES[0], "BBB"))


@pytest.mark.parametrize("value", [None, True, "1.0", 1 + 2j])
def test_invalid_original_value_types_are_not_coerced(value):
    row = held()
    row["a2_prediction"] = value
    p = Provider(**args(held_rows=[row]))
    failure(lambda: p.for_day(DATES[0], np.array([False, True])),
            "INVALID_ORIGINAL_RAW_VALUE_TYPE", (DATES[0], "BBB"))


@pytest.mark.parametrize("kind", ["base_duplicate", "held_duplicate", "physical_duplicate"])
def test_duplicate_key_or_physical_row_is_rejected(kind):
    config = args()
    if kind == "base_duplicate":
        config["base_keys"].append(config["base_keys"][0])
        reason = "DUPLICATE_BASE_KEY"
    elif kind == "held_duplicate":
        config["held_rows"].append(held())
        reason = "DUPLICATE_HELD_KEY"
    else:
        config["base_keys"][1]["row_identity"] = 0
        reason = "DUPLICATE_PHYSICAL_ROW_IDENTITY"
    failure(lambda: Provider(**config), reason)


@pytest.mark.parametrize("field,value", [("source_ref", "synthetic://other"),
    ("source_sha256", "d" * 64), ("source_namespace", "OTHER")])
def test_held_source_conflicts_do_not_select_another_source(field, value):
    row = held()
    row[field] = value
    failure(lambda: Provider(**args(held_rows=[row])), "HELD_SOURCE_PIN_MISMATCH",
            (DATES[0], "BBB"))


def test_undeclared_held_source_and_year_mismatch_fail_closed():
    failure(lambda: Provider(**args(held_refs={})), "UNDECLARED_HELD_SOURCE",
            (DATES[0], "BBB"))
    row = held(source_year=2024)
    failure(lambda: Provider(**args(held_rows=[row], held_refs={2024: ref("d", "2024")})),
            "HELD_ANNUAL_SOURCE_YEAR_MISMATCH", (DATES[0], "BBB"))


@pytest.mark.parametrize("cutoff", ["2022-01-01", DATES[0], "2026-01-01"])
def test_held_clock_failure_reports_actual_requested_key(cutoff):
    row = held()
    row["source_fit_cutoff"] = cutoff
    p = Provider(**args(held_rows=[row]))
    reason = "ORIGINAL_HELD_FIT_CLOCK_INVALID" if cutoff.startswith("2026") else (
        "ORIGINAL_HELD_FIT_CUTOFF_MISMATCH")
    error = failure(lambda: p.for_day(DATES[0], np.array([False, True])),
                    reason, (DATES[0], "BBB"))
    assert error.receipt["source_ref"]["sha256"] == "c" * 64


def test_original_uncertainty_column_is_required_not_derived_from_mean():
    row = held()
    del row["raw_uncertainty"]
    p = Provider(**args(held_rows=[row]))
    error = failure(lambda: p.for_day(DATES[0], np.array([False, True])),
                    "ORIGINAL_HELD_FIELD_MISSING", (DATES[0], "BBB"))
    assert error.receipt["field"] == "raw_uncertainty"


def test_unknown_legal_identity_is_allowed_but_alias_and_explicit_conflict_are_not():
    Provider(**args())  # No legal SID/CUSIP/class columns required.
    row = held(alias_of="OTHER")
    failure(lambda: Provider(**args(held_rows=[row])),
            "UNSUPPORTED_ALIAS_OR_TICKER_CHANGE", (DATES[0], "BBB"))
    config = args()
    config["base_keys"][0]["share_class"] = "CLASS_A"
    config["base_keys"][1]["share_class"] = "CLASS_B"
    failure(lambda: Provider(**config), "CONFLICTING_EXPLICIT_SECURITY_IDENTITY",
            (DATES[1], "AAA"))


def test_literal_ticker_axis_and_shape_conflicts_are_not_normalized():
    failure(lambda: Provider(**args(tickers=("AAA", "AAA"))),
            "UNIQUE_LITERAL_TICKER_AXIS_REQUIRED")
    failure(lambda: Provider(**args(mu=np.ones((1, 2)))),
            "EXACT_VALUE_AXIS_SHAPE_REQUIRED")
    failure(lambda: Provider(**args(base_keys=[(DATES[0], "aaa")])),
            "SOURCE_KEY_OUTSIDE_MARKET_AXES", (DATES[0], "aaa"))
    p = Provider(**args())
    failure(lambda: p.for_day(DATES[0], np.array([True, True]), tickers=TICKERS[::-1]),
            "ORDERED_MARKET_AXIS_CHANGED", (DATES[0], ""))
    failure(lambda: p.for_day(DATES[0], [1, 0]), "EXACT_BOOLEAN_REQUIRED_MASK_REQUIRED")


def test_future_and_nonexact_dates_cannot_enter_provider():
    failure(lambda: Provider(**args(dates=(DATES[0], "2026-01-02"))),
            "PRE2026_DATE_REQUIRED")
    failure(lambda: Provider(**args(dates=("2023-01-03T12:00:00", DATES[1]))),
            "NAIVE_EXACT_SESSION_DATE_REQUIRED")


def test_axis_token_stable_row_token_day_specific_and_source_bound():
    p = Provider(**args())
    first = p.for_day(DATES[0], np.array([True, False])).provenance[0]
    later = p.for_day(DATES[1], np.array([True, False])).provenance[0]
    assert first["axis_token"] == later["axis_token"]
    assert first["row_token"] != later["row_token"]
    other = Provider(**args(base_ref=ref("d", "other_base")))
    assert other.for_day(DATES[0], np.array([True, False])).provenance[0]["row_token"] != first["row_token"]
    different_cache = Provider(**args(cache_ref=ref("e", "other_cache")))
    assert different_cache.axis_tokens != p.axis_tokens


def test_constructor_snapshot_and_float32_base_do_not_round_held_values():
    config = args()
    config["mu"] = config["mu"].astype(np.float32)
    p = Provider(**config)
    config["mu"][:] = -99
    config["held_rows"][0]["a2_prediction"] = -999.
    config["base_ref"]["sha256"] = "f" * 64
    result = p.for_day(DATES[0], np.array([True, True]))
    assert result.mu[0] == float(np.float32(.7))
    assert result.mu[1] == .123456789012345
    assert result.provenance[0]["source_ref"]["sha256"] == "a" * 64


def test_provider_has_no_file_read_or_account_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider attempted I/O")
    monkeypatch.setattr(builtins, "open", forbidden)
    p = Provider(**args())
    assert p.for_day(DATES[0], np.array([True, True])).sigma[1] == .234567890123456


def metadata_only(row):
    return {name: value for name, value in row.items()
            if name not in ("a2_prediction", "raw_uncertainty")}


def test_lazy_catalog_reads_only_required_held_keys_once_per_day_batch():
    third = held(ticker="CCC")
    third["row_identity"] = 43
    calls = []
    original = [held(), third]

    def load_values(year, day, tickers):
        calls.append((year, day, tickers))
        return pd.DataFrame([row for row in original if row["ticker"] in tickers])

    config = args(tickers=("AAA", "BBB", "CCC"),
                  mu=np.array([[.7, 999., 999.], [.8, 888., 888.]]),
                  sigma=np.array([[0., 999., 999.], [.03, 888., 888.]]),
                  held_rows=[metadata_only(row) for row in original],
                  held_value_loader=load_values)
    p = Provider(**config)
    assert calls == []
    result = p.for_day(DATES[0], np.array([True, True, True]))
    assert calls == [(2023, DATES[0], ("BBB", "CCC"))]
    assert result.mu[0] == .7
    assert result.mu[1] == original[0]["a2_prediction"]
    assert result.sigma[2] == original[1]["raw_uncertainty"]
    assert all(row["value_loading"] == "REQUIRED_HELD_BATCH"
               for row in result.provenance[1:])
    # A separate actual demand requests only that exact subset, without expansion.
    calls.clear()
    partial = p.for_day(DATES[0], np.array([True, False, True]))
    assert calls == [(2023, DATES[0], ("CCC",))]
    assert np.isnan(partial.mu[1]) and len(partial.provenance) == 2


def test_lazy_loader_is_not_called_for_base_only_or_nonrequired_missing_rows():
    def forbidden(*_args):
        raise AssertionError("nonrequired held values decoded")

    p = Provider(**args(held_rows=[metadata_only(held())], held_value_loader=forbidden))
    assert p.for_day(DATES[0], np.array([True, False])).mu[0] == .7
    assert np.isnan(p.for_day(DATES[1], np.array([False, False])).mu).all()
    failure(lambda: p.for_day(DATES[1], np.array([False, True])),
            "EXACT_REQUIRED_RAW_ROW_MISSING", (DATES[1], "BBB"))


def test_lazy_missing_actual_row_is_failure_without_catalog_value_fallback():
    p = Provider(**args(held_value_loader=lambda *_: pd.DataFrame(columns=list(held()))))
    error = failure(lambda: p.for_day(DATES[0], np.array([False, True])),
                    "EXACT_REQUIRED_HELD_VALUE_ROW_MISSING", (DATES[0], "BBB"))
    assert error.receipt["query"] == dict(source_year=2023, signal_date=DATES[0],
                                         tickers=["BBB"])
    assert error.receipt["source_ref"]["sha256"] == "c" * 64


@pytest.mark.parametrize("column", ["a2_prediction", "raw_uncertainty", "row_identity"])
def test_lazy_loader_cannot_default_a_missing_actual_field(column):
    row = held()
    del row[column]
    p = Provider(**args(held_rows=[metadata_only(held())],
                        held_value_loader=lambda *_: pd.DataFrame([row])))
    error = failure(lambda: p.for_day(DATES[0], np.array([False, True])),
                    "ORIGINAL_HELD_FIELD_MISSING", (DATES[0], "BBB"))
    assert error.receipt["field"] == column


@pytest.mark.parametrize("mutation,reason", [
    ("identity", "HELD_LOADER_ROW_IDENTITY_MISMATCH"),
    ("duplicate", "DUPLICATE_HELD_LOADER_KEY"),
    ("unrequested", "HELD_LOADER_RETURNED_UNREQUESTED_KEY"),
    ("source", "HELD_LOADER_METADATA_MISMATCH"),
    ("cutoff", "HELD_LOADER_METADATA_MISMATCH"),
    ("nan", "NONFINITE_OR_NEGATIVE_ORIGINAL_REQUIRED_VALUE"),
])
def test_lazy_returned_rows_must_match_exact_requested_catalog(mutation, reason):
    rows = [held()]
    if mutation == "identity":
        rows[0]["row_identity"] = "42"  # No cast to the catalog's physical integer.
    elif mutation == "duplicate":
        rows.append(held())
    elif mutation == "unrequested":
        rows[0]["signal_date"] = DATES[1]
    elif mutation == "source":
        rows[0]["source_sha256"] = "e" * 64
    elif mutation == "cutoff":
        rows[0]["source_fit_cutoff"] = "2022-01-01"
    else:
        rows[0]["raw_uncertainty"] = np.nan
    p = Provider(**args(held_rows=[metadata_only(held())],
                        held_value_loader=lambda *_: pd.DataFrame(rows)))
    key = (DATES[1], "BBB") if mutation == "unrequested" else (DATES[0], "BBB")
    failure(lambda: p.for_day(DATES[0], np.array([False, True])), reason, key)


def test_lazy_requires_physical_catalog_identity_when_that_row_is_consumed():
    catalog = metadata_only(held())
    del catalog["row_identity"]
    calls = []
    p = Provider(**args(held_rows=[catalog],
                        held_value_loader=lambda *query: calls.append(query)))
    p.for_day(DATES[0], np.array([True, False]))
    failure(lambda: p.for_day(DATES[0], np.array([False, True])),
            "HELD_LAZY_PHYSICAL_ROW_IDENTITY_REQUIRED", (DATES[0], "BBB"))
    assert calls == []


def test_lazy_callback_failure_has_exact_requested_key_and_source():
    def broken(*_args):
        raise OSError("synthetic decoding failure")

    p = Provider(**args(held_rows=[metadata_only(held())], held_value_loader=broken))
    error = failure(lambda: p.for_day(DATES[0], np.array([False, True])),
                    "HELD_VALUE_LOADER_FAILED", (DATES[0], "BBB"))
    assert error.receipt["error_type"] == "OSError"
    assert error.receipt["source_ref"]["sha256"] == "c" * 64
    failure(lambda: Provider(**args(held_value_loader="not callable")),
            "HELD_VALUE_LOADER_CALLABLE_REQUIRED")


def test_base_cell_provenance_retains_original_cache_slice_offset():
    p = Provider(**args(cache_date_offset=417))
    first = p.for_day(DATES[0], np.array([True, False])).provenance[0]
    second = p.for_day(DATES[1], np.array([True, False])).provenance[0]
    assert first["value_cell_identity"] == dict(
        evaluation_date_index=0, original_cache_date_index=417, column=0)
    assert second["value_cell_identity"] == dict(
        evaluation_date_index=1, original_cache_date_index=418, column=0)
    assert first["value_source_ref"]["sha256"] == "b" * 64
    # Original RAW row identity stays distinct from its original cache cell.
    assert first["exact_row_identity"] == {"physical_row_identity": 0}
    for bad_offset in (-1, True, 1.0):
        failure(lambda: Provider(**args(cache_date_offset=bad_offset)),
                "NONNEGATIVE_ORIGINAL_CACHE_DATE_OFFSET_REQUIRED")
