from pathlib import Path

import pandas as pd
import pytest

from scripts.research.a2.options import independent_prices as ip


def fixture():
    dates = ip.calendar().sessions[ip.calendar().sessions >= "2025-01-02"][:21]
    panel = pd.DataFrame({"underlying_uid": ["old-uid"], "ticker": ["X"]})
    keys = pd.DataFrame({"underlying_uid": "old-uid", "ticker": "X", "session": dates, "field": "open"})
    surface = pd.DataFrame({"ticker": "X", "trade_date": dates, "moomoo_transport_code": "US.X",
                            "open": range(100, 121), "source": "MOOMOO_OPEND_RAW_PLUS_REHAB",
                            "autype": "PIT_FORWARD_REHAB_INDEX"})
    members = pd.DataFrame({"signal_date": [dates[0]], "ticker": ["X"], "cusip": ["old-uid"],
                            "moomoo_transport_code": ["US.X"]})
    return keys, panel, surface, members


def test_market_prices_survive_later_membership_and_holdings_disappearance():
    keys, panel, surface, members = fixture()
    result = ip.project_prices(keys, panel, surface, members)
    assert result.price_valid.all()
    assert result.iloc[0].identity_valid
    assert result.iloc[1:].identity_status.eq("UNKNOWN_HISTORICAL_IDENTITY").all()
    assert result.iloc[5].price == 105 and result.iloc[20].price == 120
    # No holdings input exists. More dated identity evidence may qualify more
    # labels, but cannot change requested price keys or their market values.
    full = pd.concat([members.assign(signal_date=d) for d in keys.session], ignore_index=True)
    qualified = ip.project_prices(keys, panel, surface, full)
    unchanged = ip.KEY + ["price", "price_valid", "source", "price_kind"]
    pd.testing.assert_frame_equal(result[unchanged], qualified[unchanged])
    assert qualified.identity_valid.all()


def test_unique_static_transport_does_not_certify_temporal_uid():
    keys, panel, surface, members = fixture()
    result = ip.project_prices(keys, panel, surface, members)
    assert result.iloc[5].price_valid and result.iloc[5].price == 105
    assert result.iloc[5].transport_identity_status == "BOUND_STATIC_ROUTE_NOT_TEMPORAL_UID_CERTIFICATION"
    assert not result.iloc[5].identity_valid
    assert result.iloc[5].identity_status == "UNKNOWN_HISTORICAL_IDENTITY"


def test_missing_middle_never_creates_or_relabels_an_observation():
    keys, panel, surface, members = fixture()
    result = ip.project_prices(keys, panel, surface.drop(index=[2, 4]), members)
    assert len(result) == 21
    assert not result.iloc[2].price_valid
    assert result.iloc[0].price_valid and result.iloc[20].price_valid
    assert result.iloc[5].session == keys.iloc[5].session
    assert result.iloc[5].price == 105
    assert result.action_valid.all()  # Action source validity is not price completeness.


def test_multicusip_ticker_requires_dated_identity_and_never_stitches_uid():
    keys, panel, surface, members = fixture()
    future_identity = members.assign(signal_date=keys.iloc[5].session, cusip="new-uid")
    result = ip.project_prices(keys, panel, surface, pd.concat([members, future_identity]))
    assert result.iloc[0].identity_valid
    assert result.iloc[1].identity_status == "UNKNOWN_HISTORICAL_IDENTITY"
    assert result.iloc[5].identity_status == "CHANGED_HISTORICAL_UID"
    assert result.iloc[5].underlying_uid == "old-uid" and result.iloc[5].price_valid


@pytest.mark.parametrize("change,error", [
    (lambda k: k.assign(session=pd.Timestamp("2026-01-02")), "NON_PRE2026"),
    (lambda k: k.assign(field="close"), "UNBOUND_FIELD"),
    (lambda k: k.assign(underlying_uid="unknown"), "UNBOUND_OPPORTUNITY"),
    (lambda k: k.assign(session=pd.Timestamp("2025-01-05")), "NON_TRADING_SESSION"),
])
def test_invalid_keys_reject_before_source_open(monkeypatch, change, error):
    keys, panel, _, _ = fixture()
    monkeypatch.setattr(ip, "_bytes", lambda *a: pytest.fail("source opened before reject"))
    with pytest.raises(ValueError, match=error):
        ip.load_independent_prices(change(keys), panel)


def test_deterministic_keys_input_order_and_duplicate_cache_hit():
    keys, panel, surface, members = fixture()
    expected = ip.project_prices(keys, panel, surface, members)
    shuffled = pd.concat([keys.iloc[::-1], keys.iloc[:2]], ignore_index=True)
    actual = ip.project_prices(shuffled, panel, surface.iloc[::-1], members)
    pd.testing.assert_frame_equal(expected, actual)


def test_secondary_and_double_adjustment_not_admitted():
    keys, panel, surface, members = fixture()
    with pytest.raises(ValueError, match="SOURCE_LEVEL"):
        ip.project_prices(keys, panel, surface.assign(source="SECONDARY"), members)
    with pytest.raises(ValueError, match="ADJUSTMENT_LEVEL"):
        ip.project_prices(keys, panel, surface.assign(autype="qfq"), members)
    result = ip.project_prices(keys, panel, surface, members)
    assert result.price.tolist() == surface.open.tolist()


def test_frozen_loader_extraction_executes_no_import_or_build():
    functions = ["require", "sha256_file", "canonical_json_hash", "content_hash",
                 "normalize_adjusted_frame", "validate_surface_frame", "verify_manifest_contract", "load_frozen_surface"]
    constants = ["SURFACE_NAME", "END_EXCLUSIVE", "MAX_OUTPUT_DATE", "OUTPUT_COLUMNS", "STRING_COLUMNS", "FLOAT_COLUMNS"]
    source = "import unavailable_module\nraise RuntimeError('build')\n"
    source += "\n".join(f"{name} = None" for name in constants)
    source += "\n" + "\n".join(f"def {name}():\n    return 'pure'" for name in functions)
    assert ip._pure_loader(source.encode(), Path("manifest.json"))["load_frozen_surface"]() == "pure"
