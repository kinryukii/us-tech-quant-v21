"""Synthetic source-bound cash binding checks. No data, models or account replay."""
import copy
import hashlib
from dataclasses import asdict

import pandas as pd
import pytest
from scripts.research.a2.data.joint_cash_bindings import (
    bind_cash_entitlements, source_derived_security_id,
)
from scripts.v22.corporate_action_transition_r1 import (
    canonical_bytes, apply_entitlement_lifecycle, RAW_OLD_SHARE_COORDINATE,
    USD_PER_RAW_OLD_SHARE,
)


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def clock(day, hour=16, minute=0):
    return str((pd.Timestamp(day) + pd.Timedelta(hours=hour, minutes=minute)).tz_localize("America/New_York").tz_convert("UTC"))


def case(*, schema=1, record="2023-01-27", pay="2023-03-03", amount=.1, accepted=False):
    # This entire session calendar is a caller-provided synthetic source fixture.
    days = pd.bdate_range("2023-01-02", "2025-12-31")
    days = days[~days.isin(pd.to_datetime(["2024-05-27", "2025-04-18"]))]
    calendar = [str(d.date()) for d in days]
    record_pos = calendar.index(record)
    ex = calendar[record_pos-1] if record < "2024-05-28" else record
    prior = calendar[calendar.index(ex)-1]
    issuer="Alpha Inc."; ticker="AAA"; listing="NYSE:AAA"
    sid = "PIT_ALPHA_COMMON_001" if accepted else source_derived_security_id(issuer,ticker,listing)
    entry=dict(security_id=sid,identity_kind="ACCEPTED_PIT_SECURITY_ID" if accepted else "SOURCE_DERIVED_ISSUER_COMMON_CLASS",issuer=issuer,ticker=ticker,listing_identity=listing,security_type="COMMON_STOCK",source_reference="https://issuer.example/identity",source_fingerprint="a"*64,available_at="2022-12-02T23:59:59Z")
    entry["identity_payload_sha256"]=digest({k:entry[k] for k in ("security_id","identity_kind","issuer","ticker","listing_identity","security_type")})
    key="AAA_FAKE"
    payload=dict(id=key,issuer=issuer,listing_identity=listing,source_url="https://issuer.example/dividend",cash_per_common_share=amount,currency="USD",currency_basis="INFERRED_USD_CONTEXT",record_date=record,pay_date=pay,publication_date="2022-12-01",candidate_ex_date=ex,availability_bound={"available_at":"2022-12-02T23:59:59Z","official_exact_clock":False},cash_is_gross_announced_amount=True,raw_bytes_available=False,raw_sha256=None)
    if schema==2:
        payload=dict(event_key=key,ticker=ticker,issuer=issuer,listed_exchange="NYSE",source_url="https://issuer.example/earnings",cash_per_raw_ex_pretrade_common_share=amount,currency="USD",currency_confidence="INFERRED_USD",amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,security_type="COMMON_STOCK",record_date=record,scheduled_pay_date=pay,publication_date="2024-05-22",available_at_upper_bound="2024-05-23T23:59:59Z",ex_date_binding={"value":ex,"issuer_directly_declared":False,"status":"CALLER_VENDOR_DATE_NOT_DIRECT_ISSUER_EX_DATE"},split_unit_evidence={"issuer_declared_pre_split_dividend":.1,"issuer_declared_post_split_dividend":amount,"cash_basis_for_ex_"+record.replace("-","_"):"POST_SPLIT_RAW_COMMON_SHARE"})
    envelope=dict(path="FAKE_ONLY/cash_fact.json",sha256=digest(payload),payload=payload)
    vendor=dict(ticker=ticker,effective_date=ex,reason="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY",source_reference="FAKE_ONLY/ACCOUNT_EVENT_BINDING.json",source_fingerprint="b"*64)
    price=dict(ticker=ticker,security_id=sid,signal_date=prior,raw_close=100.,available_at=clock(prior),source_fingerprint="c"*64,price_coordinate="RAW_CLOSE",quantity_coordinate=RAW_OLD_SHARE_COORDINATE)
    classification=dict(family="CASH_DIVIDEND",vendor_event_source_fingerprint="b"*64,statement_fact_sha256=envelope["sha256"],vendor_cash_per_raw_old_share=amount,non_cash_flags_absent=True,amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,classification_source_fingerprint="d"*64,vendor_typed_cash_field_source_sha256="e"*64)
    return dict(fact_projections=[envelope],calendar=calendar,calendar_binding={"status":"SOURCE_BOUND_LEGAL_SESSION_CALENDAR","session_dates_sha256":digest(calendar),"source_reference":"FAKE_ONLY/session_calendar.json","source_fingerprint":"f"*64},unsupported_events=[vendor],security_bindings={ticker:entry},pre_ex_raw_closes={key:price},rule_sources={"TPLUS2":{"source_reference":"https://rules.example/17-19","source_fingerprint":"1"*64,"effective_from":"2017-09-05","effective_until_exclusive":"2024-05-28","kind":"FINRA_17_19_NORMAL_SMALL_CASH"},"TPLUS1":{"source_reference":"https://rules.example/24-04","source_fingerprint":"2"*64,"effective_from":"2024-05-28","kind":"FINRA_24_04_NORMAL_SMALL_CASH"}},cash_event_classification={(ticker,ex,"b"*64):classification})


def refresh_fact(inputs):
    envelope=inputs["fact_projections"][0];envelope["sha256"]=digest(envelope["payload"])
    for c in inputs["cash_event_classification"].values():c["statement_fact_sha256"]=envelope["sha256"]


def test_exact_cash_classification_removes_only_mapped_key_without_mutating_inputs():
    x=case();original=copy.deepcopy(x)
    x["unsupported_events"].extend([
        {**x["unsupported_events"][0],"source_fingerprint":"9"*64},
        {**x["unsupported_events"][0],"reason":"RAW_LARGE_MOVE_DIAGNOSTIC","source_fingerprint":"6"*64},
        {"ticker":"BBB","effective_date":"2023-01-26","reason":"SPINOFF","source_fingerprint":"b"*64},
    ])
    before=copy.deepcopy(x);r=bind_cash_entitlements(**x)
    assert x==before and original["unsupported_events"][0]==x["unsupported_events"][0]
    assert len(r.events)==1 and len(r.removal_keys)==1 and len(r.remaining_unsupported_events)==3
    assert r.source_binding["event_fingerprints"]==[r.events[0].event_fingerprint]
    assert r.proofs[0]["broker_payment"]=="NOT_OBSERVED"
    assert "INFERRED" in r.proofs[0]["exchange_received_notice"]


def test_generic_unknown_vendor_event_is_retained_even_with_matching_cash_fact():
    x=case();x.pop("cash_event_classification");r=bind_cash_entitlements(**x)
    assert len(r.events)==1 and not r.removal_keys
    assert r.remaining_unsupported_events==tuple(x["unsupported_events"])


@pytest.mark.parametrize("change",["wrong_fact_sha","wrong_vendor_sha","wrong_amount","non_cash_flags"])
def test_cash_classification_guard_preserves_unknowns(change):
    x=case();c=next(iter(x["cash_event_classification"].values()))
    c[{"wrong_fact_sha":"statement_fact_sha256","wrong_vendor_sha":"vendor_event_source_fingerprint","wrong_amount":"vendor_cash_per_raw_old_share","non_cash_flags":"non_cash_flags_absent"}[change]]={"wrong_fact_sha":"9"*64,"wrong_vendor_sha":"9"*64,"wrong_amount":9.,"non_cash_flags":False}[change]
    r=bind_cash_entitlements(**x);assert not r.removal_keys and len(r.remaining_unsupported_events)==1


@pytest.mark.parametrize("record,expected",[("2024-05-24","2024-05-23"),("2024-05-28","2024-05-28")])
def test_tplus_boundary_uses_frozen_calendar_and_rule_interval(record,expected):
    r=bind_cash_entitlements(**case(record=record,pay="2024-06-01"));assert r.events[0].ex_date==expected
    rule=r.proofs[0]["ex_assumption"]["rule"];assert rule["kind"]==( "FINRA_24_04_NORMAL_SMALL_CASH" if record=="2024-05-28" else "FINRA_17_19_NORMAL_SMALL_CASH")


def test_non_session_record_is_blocked_and_not_rolled():
    x=case();x["fact_projections"][0]["payload"]["record_date"]="2023-01-28";refresh_fact(x)
    r=bind_cash_entitlements(**x);assert not r.events and r.blocked and r.remaining_unsupported_events


@pytest.mark.parametrize("mutation",["NaT_publication","late_available","available_at_ex_open","late_close","future_close","wrong_ex","missing_identity"])
def test_missing_late_or_misaligned_inputs_block_without_source_upgrade(mutation):
    x=case();p=x["fact_projections"][0]["payload"]
    if mutation=="NaT_publication":p["publication_date"]="NaT"
    elif mutation=="late_available":p["availability_bound"]["available_at"]="2023-01-26T15:00:00Z"
    elif mutation=="available_at_ex_open":p["availability_bound"]["available_at"]=clock("2023-01-26",9,30)
    elif mutation=="late_close":x["pre_ex_raw_closes"]["AAA_FAKE"]["available_at"]="2023-01-25T21:00:01Z"
    elif mutation=="future_close":x["pre_ex_raw_closes"]["AAA_FAKE"]["signal_date"]="2023-01-26"
    elif mutation=="wrong_ex":p["candidate_ex_date"]="2023-01-27"
    else:x["security_bindings"]={}
    refresh_fact(x);r=bind_cash_entitlements(**x)
    assert not r.events and len(r.blocked)==1 and r.remaining_unsupported_events==tuple(x["unsupported_events"])


@pytest.mark.parametrize("amount",[25.,30.])
def test_at_or_above_25_percent_is_due_bill_blocked(amount):
    r=bind_cash_entitlements(**case(amount=amount));assert not r.events
    assert "LARGE_CASH_DUE_BILL" in r.blocked[0]["reason"]


def test_nvda_like_post_split_one_cent_is_not_multiplied_again():
    r=bind_cash_entitlements(**case(schema=2,record="2024-06-11",pay="2024-06-28",amount=.01))
    assert r.events[0].cash_per_old_share==.01
    app=apply_entitlement_lifecycle(r.events,{r.events[0].old_security_id:10.},0.,execution_date=pd.Timestamp("2024-06-11"),session_open_at=pd.Timestamp(clock("2024-06-11",9,30)),security_tickers=r.security_tickers,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,enabled=True)
    assert app.cash==0. and app.receivable_value_usd==pytest.approx(.1)


def test_hpe_like_holiday_expected_pay_uses_first_legal_session_without_observed_paid_claim():
    r=bind_cash_entitlements(**case(record="2025-03-21",pay="2025-04-18"));event=r.events[0];positions={event.old_security_id:10.}
    ex=apply_entitlement_lifecycle(r.events,positions,0.,execution_date=pd.Timestamp(event.ex_date),session_open_at=pd.Timestamp(clock(event.ex_date,9,30)),security_tickers=r.security_tickers,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,enabled=True)
    before=apply_entitlement_lifecycle(r.events,positions,ex.cash,execution_date=pd.Timestamp("2025-04-17"),session_open_at=pd.Timestamp(clock("2025-04-17",9,30)),security_tickers=r.security_tickers,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,state=ex.state,enabled=True)
    paid=apply_entitlement_lifecycle(r.events,positions,before.cash,execution_date=pd.Timestamp("2025-04-21"),session_open_at=pd.Timestamp(clock("2025-04-21",9,30)),security_tickers=r.security_tickers,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,state=before.state,enabled=True)
    assert before.cash==0. and before.receivable_value_usd==1.
    assert paid.cash==1. and paid.receivable_value_usd==0.
    assert r.proofs[0]["broker_payment"]=="NOT_OBSERVED"


@pytest.mark.parametrize("sid",["FROZEN_VENDOR:AAA","SOURCE_ISSUER_COMMON_CLASS:"+"9"*64,"UNKNOWN"])
def test_placeholder_or_arbitrary_source_derived_uid_fails_even_when_payload_hash_matches(sid):
    x=case();entry=x["security_bindings"]["AAA"];entry["security_id"]=sid
    entry["identity_payload_sha256"]=digest({k:entry[k] for k in ("security_id","identity_kind","issuer","ticker","listing_identity","security_type")})
    r=bind_cash_entitlements(**x);assert not r.events and r.blocked


def test_stable_uid_ignores_announcement_and_identity_source_hash_changes():
    x=case();y=copy.deepcopy(x);y["security_bindings"]["AAA"]["source_fingerprint"]="7"*64;y["fact_projections"][0]["payload"]["source_url"]="https://issuer.example/revision";refresh_fact(y)
    a=bind_cash_entitlements(**x);b=bind_cash_entitlements(**y)
    assert a.events[0].old_security_id==b.events[0].old_security_id
    assert a.events[0].event_id==b.events[0].event_id
    assert a.events[0].event_fingerprint!=b.events[0].event_fingerprint


def test_accepted_pit_id_is_reused_but_wrong_declared_issuer_is_blocked():
    x=case(accepted=True);assert bind_cash_entitlements(**x).events[0].old_security_id=="PIT_ALPHA_COMMON_001"
    x["security_bindings"]["AAA"]["issuer"]="Other Inc."
    r=bind_cash_entitlements(**x);assert not r.events


@pytest.mark.parametrize("revised_pay",[False,True])
def test_duplicate_or_revised_economic_event_is_not_silently_selected(revised_pay):
    x=case();duplicate=copy.deepcopy(x["fact_projections"][0]);duplicate["payload"]["id"]="OTHER_REVISION";duplicate["payload"]["pay_date"]="2023-03-10" if revised_pay else duplicate["payload"]["pay_date"];duplicate["sha256"]=digest(duplicate["payload"]);x["fact_projections"].append(duplicate);x["pre_ex_raw_closes"]["OTHER_REVISION"]=copy.deepcopy(x["pre_ex_raw_closes"]["AAA_FAKE"])
    r=bind_cash_entitlements(**x);assert not r.events and len(r.blocked)==2 and r.remaining_unsupported_events


def test_physical_byte_guard_must_bind_parsed_payload_without_binder_file_reads():
    x=case();envelope=x["fact_projections"][0];payload_hash=digest(envelope["payload"]);envelope["sha256"]="8"*64
    assert not bind_cash_entitlements(**x).events
    envelope["guard"]={"status":"HASH_VERIFIED_PAYLOAD","path":envelope["path"],"sha256":envelope["sha256"],"payload_sha256":payload_hash}
    for c in x["cash_event_classification"].values():c["statement_fact_sha256"]=envelope["sha256"]
    r=bind_cash_entitlements(**x);assert r.events and r.proofs[0]["projection"]["physical_bytes_read_by_binder"] is False


@pytest.mark.parametrize("mutation",["rule","calendar","adjusted_close","wrong_share_quantity"])
def test_frozen_rule_calendar_and_raw_share_guards(mutation):
    x=case()
    if mutation=="rule":x["rule_sources"]["TPLUS1"]["effective_from"]="2024-05-29"
    elif mutation=="calendar":x["calendar"].remove("2023-01-25")
    elif mutation=="adjusted_close":x["pre_ex_raw_closes"]["AAA_FAKE"]["price_coordinate"]="ADJUSTED_CLOSE"
    else:x["pre_ex_raw_closes"]["AAA_FAKE"]["quantity_coordinate"]="RESEARCH_SCALED_SHARES"
    if mutation in ("rule","calendar"):
        with pytest.raises(ValueError):bind_cash_entitlements(**x)
    else:assert not bind_cash_entitlements(**x).events


def test_ambiguous_same_key_forensic_record_keeps_all_original_events():
    x=case();x["unsupported_events"].append({**x["unsupported_events"][0],"reason":"RAW_LARGE_MOVE_DIAGNOSTIC"})
    r=bind_cash_entitlements(**x)
    assert r.events and not r.removal_keys
    assert r.remaining_unsupported_events==tuple(x["unsupported_events"])
    assert r.source_binding["manifest"]["ambiguous_vendor_keys_preserved"]


def test_pre26_announced_crossyear_pay_is_unpaid_receivable_without_future_observation():
    x=case(record="2025-12-19",pay="2026-01-02")
    p=x["fact_projections"][0]["payload"];p["publication_date"]="2025-12-01";p["availability_bound"]["available_at"]="2025-12-02T23:59:59Z";refresh_fact(x)
    r=bind_cash_entitlements(**x);event=r.events[0];positions={event.old_security_id:10.}
    ex=apply_entitlement_lifecycle(r.events,positions,0.,execution_date=pd.Timestamp(event.ex_date),session_open_at=pd.Timestamp(clock(event.ex_date,9,30)),security_tickers=r.security_tickers,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,enabled=True)
    yearend=apply_entitlement_lifecycle(r.events,positions,ex.cash,execution_date=pd.Timestamp("2025-12-31"),session_open_at=pd.Timestamp(clock("2025-12-31",9,30)),security_tickers=r.security_tickers,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,state=ex.state,enabled=True)
    assert event.pay_date=="2026-01-02" and yearend.cash==0. and yearend.receivable_value_usd==1.
    assert not yearend.state.paid_event_ids
    assert all(pd.Timestamp(d)<pd.Timestamp("2026-01-01") for d in x["calendar"])


@pytest.mark.parametrize("field",["publication","ex_record"])
def test_future_observation_or_ex_is_rejected_while_known_future_pay_is_allowed(field):
    x=case();p=x["fact_projections"][0]["payload"]
    if field=="publication":p["publication_date"]="2026-01-01";p["availability_bound"]["available_at"]="2026-01-02T23:59:59Z"
    else:p["record_date"]="2026-01-26";p["candidate_ex_date"]="2026-01-26"
    refresh_fact(x);r=bind_cash_entitlements(**x)
    assert not r.events and r.blocked and r.remaining_unsupported_events



def ads_case():
    """Fake source-declared ADS terms; cash amount is per actual ADS position."""
    x = case(schema=2, record="2024-06-11", pay="2024-06-28", amount=.3966)
    payload = x["fact_projections"][0]["payload"]
    payload.pop("split_unit_evidence")
    payload.update(security_type="AMERICAN_DEPOSITARY_SHARE",
                   cash_per_raw_ex_pretrade_common_share=None,
                   cash_per_raw_ex_pretrade_ads=.3966,
                   ads_unit_evidence={"unit_status": "SOURCE_DECLARED_PER_ADS",
                       "source_unit": "USD_PER_ADS_GROSS_BEFORE_APPLICABLE_FEES",
                       "cash_per_raw_ads": .3966,
                       "source_reference": payload["source_url"],
                       "ordinary_shares_per_ads": 6,
                       "cash_per_raw_ordinary_share_usd": .0661})
    entry = x["security_bindings"]["AAA"]
    entry["security_type"] = "AMERICAN_DEPOSITARY_SHARE"
    entry["security_id"] = source_derived_security_id(entry["issuer"], "AAA", "NYSE:AAA", "AMERICAN_DEPOSITARY_SHARE")
    entry["identity_payload_sha256"] = digest({k: entry[k] for k in ("security_id", "identity_kind", "issuer", "ticker", "listing_identity", "security_type")})
    x["pre_ex_raw_closes"]["AAA_FAKE"]["security_id"] = entry["security_id"]
    refresh_fact(x)
    return x


def test_ads_requires_explicit_true_opt_in_and_preserves_vendor_without_it():
    x = ads_case()
    before = copy.deepcopy(x)
    for option in (False, None, 1, "true"):
        r = bind_cash_entitlements(**x, allow_ads=option)
        assert not r.events and "ADS_EXPLICIT_OPT_IN_REQUIRED" in r.blocked[0]["reason"]
        assert r.remaining_unsupported_events == tuple(x["unsupported_events"])
    assert x == before


def test_ads_direct_gross_cash_follows_ads_units_without_ratio_multiplier_or_deduction():
    x = ads_case(); before = copy.deepcopy(x)
    r = bind_cash_entitlements(**x, allow_ads=True); event = r.events[0]
    assert x == before and event.cash_per_old_share == .3966 and len(r.removal_keys) == 1
    assert event.old_security_id.startswith("SOURCE_ISSUER_ADS_CLASS:")
    for ads_quantity in (3., 9.):
        applied = apply_entitlement_lifecycle(r.events, {event.old_security_id: ads_quantity}, 0.,
            execution_date=pd.Timestamp(event.ex_date), session_open_at=pd.Timestamp(clock(event.ex_date, 9, 30)),
            security_tickers=r.security_tickers, quantity_coordinate=RAW_OLD_SHARE_COORDINATE, enabled=True)
        assert applied.cash == 0. and applied.receivable_value_usd == pytest.approx(ads_quantity * .3966)
        assert applied.receivable_value_usd != pytest.approx(ads_quantity * .3966 * 6)
    assert r.proofs[0]["cash_deductions"] == {"depositary_fees": "UNKNOWN", "withholding": "UNKNOWN", "actual_broker_cash": "NOT_OBSERVED"}
    assert "NO_FEE_OR_WITHHOLDING_ESTIMATE" in r.proofs[0]["gross_cash_basis"]
    assert r.proofs[0]["broker_payment"] == "NOT_OBSERVED"


@pytest.mark.parametrize("mutation", ["ordinary_as_ads", "common_field_present", "missing_ads_amount", "missing_direct_unit", "different_source", "invalid_ratio", "unbound_class"])
def test_ads_ordinary_units_and_incomplete_proof_are_blocked(mutation):
    x = ads_case(); p = x["fact_projections"][0]["payload"]
    if mutation == "ordinary_as_ads":
        p["cash_per_raw_ex_pretrade_ads"] = .0661; p["ads_unit_evidence"]["cash_per_raw_ads"] = .0661
    elif mutation == "common_field_present": p["cash_per_raw_ex_pretrade_common_share"] = .0661
    elif mutation == "missing_ads_amount": p.pop("cash_per_raw_ex_pretrade_ads")
    elif mutation == "missing_direct_unit": p["ads_unit_evidence"]["unit_status"] = "INFERRED_FROM_ORDINARY_SHARE_ONLY"
    elif mutation == "different_source": p["ads_unit_evidence"]["source_reference"] = "https://other.example/source"
    elif mutation == "invalid_ratio": p["ads_unit_evidence"]["ordinary_shares_per_ads"] = True
    else:
        entry = x["security_bindings"]["AAA"]; entry["security_type"] = "COMMON_STOCK"
        entry["identity_payload_sha256"] = digest({k: entry[k] for k in ("security_id", "identity_kind", "issuer", "ticker", "listing_identity", "security_type")})
    refresh_fact(x); r = bind_cash_entitlements(**x, allow_ads=True)
    assert not r.events and r.blocked and r.remaining_unsupported_events == tuple(x["unsupported_events"])


def test_legacy_common_share_schema_cannot_be_relabeled_as_ads():
    x = case(); x["fact_projections"][0]["payload"]["security_type"] = "AMERICAN_DEPOSITARY_SHARE"
    refresh_fact(x); r = bind_cash_entitlements(**x, allow_ads=True)
    assert not r.events and "ADS_COMMON_SHARE_SCHEMA_AMBIGUOUS" in r.blocked[0]["reason"]


def test_common_identity_default_is_exact_and_ads_is_separate_class_ontology():
    common = source_derived_security_id("Alpha Inc.", "AAA", "NYSE:AAA")
    assert common == "SOURCE_ISSUER_COMMON_CLASS:" + digest({"issuer": "Alpha Inc.", "venue": "NYSE", "common_class": "COMMON_STOCK"})
    assert common == source_derived_security_id("Alpha Inc.", "AAA", "NYSE:AAA", "COMMON_STOCK")
    ads = source_derived_security_id("Alpha Inc.", "AAA", "NYSE:AAA", "AMERICAN_DEPOSITARY_SHARE")
    assert ads != common and ads == "SOURCE_ISSUER_ADS_CLASS:" + digest({"issuer": "Alpha Inc.", "venue": "NYSE", "common_class": "AMERICAN_DEPOSITARY_SHARE"})


def test_nyse_american_common_class_preserves_declared_venue_and_exact_listing():
    x = case(schema=2, record="2024-06-11", pay="2024-06-28")
    p = x["fact_projections"][0]["payload"]; p["listed_exchange"] = "NYSE_AMERICAN"
    entry = x["security_bindings"]["AAA"]; entry["listing_identity"] = "NYSE_AMERICAN:AAA"
    entry["security_id"] = source_derived_security_id(entry["issuer"], "AAA", entry["listing_identity"])
    entry["identity_payload_sha256"] = digest({k: entry[k] for k in ("security_id", "identity_kind", "issuer", "ticker", "listing_identity", "security_type")})
    x["pre_ex_raw_closes"]["AAA_FAKE"]["security_id"] = entry["security_id"]
    refresh_fact(x); r = bind_cash_entitlements(**x)
    assert r.events and r.proofs[0]["identity"]["identity"]["listing_identity"] == "NYSE_AMERICAN:AAA"
    assert r.events[0].old_security_id != source_derived_security_id(entry["issuer"], "AAA", "NYSE:AAA")
    entry["listing_identity"] = "NYSE:AAA"
    entry["identity_payload_sha256"] = digest({k: entry[k] for k in ("security_id", "identity_kind", "issuer", "ticker", "listing_identity", "security_type")})
    assert not bind_cash_entitlements(**x).events


@pytest.mark.parametrize("listing", ["NYSE American:AAA", "NYSE_AMERICAN:OTHER", "ARBITRARY:AAA"])
def test_listing_identity_requires_explicit_normalized_venue_and_exact_ticker(listing):
    with pytest.raises(ValueError): source_derived_security_id("Alpha Inc.", "AAA", listing)


@pytest.mark.parametrize("field", ["amount_unit", "quantity_coordinate"])
def test_malformed_common_coordinates_retain_original_default_reason(field):
    x = case(schema=2, record="2024-06-11", pay="2024-06-28")
    x["fact_projections"][0]["payload"][field] = "WRONG_COORDINATE"
    refresh_fact(x); result = bind_cash_entitlements(**x)
    assert not result.events and result.blocked[0]["reason"] == "COMMON_SHARE_CASH_COORDINATE_NOT_BOUND"
    assert result.remaining_unsupported_events == tuple(x["unsupported_events"])


def _xp_precedence_case():
    x=case(record="2023-09-12",pay="2023-09-25",amount=.58)
    issuer="Fictional XP Inc.";ticker="XP";key="XP_FAKE";listing="NASDAQ:XP"
    sid=source_derived_security_id(issuer,ticker,listing)
    identity=dict(security_id=sid,identity_kind="SOURCE_DERIVED_ISSUER_COMMON_CLASS",
        issuer=issuer,ticker=ticker,listing_identity=listing,security_type="COMMON_STOCK",
        security_class="CLASS_A_COMMON_SHARES",source_reference="https://issuer.example/FAKE_class",
        source_fingerprint="a"*64,available_at="2023-04-28T00:00:00Z")
    identity["identity_payload_sha256"]=digest({k:identity[k] for k in
        ("security_id","identity_kind","issuer","ticker","listing_identity","security_type")})
    payload=dict(event_key=key,ticker=ticker,issuer=issuer,listed_exchange="NASDAQ",
        security_type="COMMON_STOCK",security_class="CLASS_A_COMMON_SHARES",
        source_url="https://issuer.example/FAKE_cash",currency="USD",currency_confidence="EXPLICIT_USD",
        amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        cash_per_raw_ex_pretrade_common_share=.58,record_date="2023-09-12",
        scheduled_pay_date="2023-09-25",publication_date="2023-09-01",
        available_at_upper_bound="2023-09-03T00:00:00Z",
        ex_date_binding={"value":"2023-09-11","issuer_direct":False})
    fact=dict(path="FAKE_ONLY/XP_fact.json",sha256=digest(payload),payload=payload,
              original_statement_source_sha256="8"*64)
    classification=dict(next(iter(x["cash_event_classification"].values())),
        statement_fact_sha256=fact["sha256"],vendor_cash_per_raw_old_share=.58498,
        vendor_cash_field="per_cash_div",vendor_row={"per_cash_div":"0.58498"},original_statement_source_sha256="8"*64)
    classification["classification_source_fingerprint"]=digest(
        {k:v for k,v in classification.items() if k!="classification_source_fingerprint"})
    x.update(fact_projections=[fact],security_bindings={ticker:identity},
        pre_ex_raw_closes={key:dict(ticker=ticker,security_id=sid,signal_date="2023-09-08",
            raw_close=100.,available_at=clock("2023-09-08"),source_fingerprint="c"*64,
            price_coordinate="RAW_CLOSE",quantity_coordinate=RAW_OLD_SHARE_COORDINATE)},
        unsupported_events=[dict(x["unsupported_events"][0],ticker=ticker)],
        cash_event_classification={(ticker,"2023-09-11","b"*64):classification})
    scope=dict(ticker=ticker,effective_date="2023-09-11",fact_key=key,
        vendor_event_source_fingerprint="b"*64,original_statement_source_sha256="8"*64,
        statement_fact_sha256=fact["sha256"],statement_payload_sha256=digest(payload),
        security_id=sid,security_class="CLASS_A_COMMON_SHARES",security_type="COMMON_STOCK",
        listing_identity=listing,identity_payload_sha256=identity["identity_payload_sha256"],
        amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        issuer_cash_per_raw_old_share=.58,vendor_cash_per_raw_old_share=.58498,
        vendor_typed_cash_field_source_sha256="e"*64,vendor_cash_field="per_cash_div",
        non_cash_flags_absent=True)
    policy=dict(schema_version=1,policy_id="XP_2023_09_11_SOURCE_DECLARED_GROSS_R4",
        stage="continuation/cash_r4",accounting_authority="SOURCE_DECLARED_GROSS",
        numeric_conflict="RETAIN_UNRECONCILED_VENDOR_DIAGNOSTIC",scope=scope)
    x["source_precedence_policy"]=dict(path="FAKE_ONLY/policy.json",sha256=digest(policy),
        payload=policy,payload_sha256=digest(policy))
    return x


def _refresh_precedence_policy(x):
    e=x["source_precedence_policy"];e["sha256"]=e["payload_sha256"]=digest(e["payload"])


def test_r4_default_mismatch_stays_unknown_and_explicit_policy_is_auditable():
    x=_xp_precedence_case();legacy=copy.deepcopy(x);legacy.pop("source_precedence_policy")
    a=bind_cash_entitlements(**legacy);b=bind_cash_entitlements(**legacy,source_precedence_policy=None)
    assert asdict(a)==asdict(b) and a.events and not a.removal_keys
    before=copy.deepcopy(x);r=bind_cash_entitlements(**x)
    assert x==before and len(r.removal_keys)==1 and not r.remaining_unsupported_events
    assert r.events[0].cash_per_old_share==.58
    metadata=r.source_binding["manifest"]["source_precedence"]
    assert metadata["qualification_basis"]=="SOURCE_DECLARED_GROSS" and metadata["policy_applied"] is True
    conflict=metadata["numeric_conflict_diagnostics"][0]
    assert conflict["vendor_cash_per_raw_old_share"]==.58498
    assert conflict["issuer_cash_per_raw_old_share"]==.58
    assert conflict["vendor_numeric_conflict_reconciled"] is False and conflict["final_paid_rate_verified"] is False


@pytest.mark.parametrize("field,value",[
    ("effective_date","2023-09-12"),("security_class","OTHER_COMMON"),
    ("issuer_cash_per_raw_old_share",.59),("vendor_cash_per_raw_old_share",.58497),
    ("quantity_coordinate","SPLIT_ADJUSTED_SHARES"),("non_cash_flags_absent",False)])
def test_r4_fixed_policy_scope_is_not_relaxed_even_with_rehashed_payload(field,value):
    x=_xp_precedence_case();x["source_precedence_policy"]["payload"]["scope"][field]=value
    _refresh_precedence_policy(x)
    with pytest.raises(ValueError,match="SOURCE_PRECEDENCE"):bind_cash_entitlements(**x)


def test_r4_canonical_policy_digest_is_recomputed_not_shape_checked():
    x=_xp_precedence_case();x["source_precedence_policy"]["payload_sha256"]="9"*64
    with pytest.raises(ValueError,match="CANONICAL_PAYLOAD"):bind_cash_entitlements(**x)


@pytest.mark.parametrize("field",[
    "vendor_event_source_fingerprint","original_statement_source_sha256","statement_fact_sha256",
    "statement_payload_sha256","identity_payload_sha256","vendor_typed_cash_field_source_sha256"])
def test_r4_exact_dynamic_binding_changes_keep_vendor_unknown(field):
    x=_xp_precedence_case();x["source_precedence_policy"]["payload"]["scope"][field]="9"*64
    _refresh_precedence_policy(x);r=bind_cash_entitlements(**x)
    assert not r.removal_keys and len(r.remaining_unsupported_events)==1
    assert r.source_binding["manifest"]["source_precedence"]["policy_applied"] is False


@pytest.mark.parametrize("mutation",["duplicate_key","forensic","noncash","wrong_identity_class","duplicate_fact","late_publication"])
def test_r4_policy_preserves_ambiguity_noncash_and_existing_pit_gates(mutation):
    x=_xp_precedence_case()
    if mutation=="duplicate_key":x["unsupported_events"].append(dict(x["unsupported_events"][0]))
    elif mutation=="forensic":x["unsupported_events"][0]["reason"]="RAW_LARGE_MOVE_DIAGNOSTIC"
    elif mutation=="noncash":next(iter(x["cash_event_classification"].values()))["non_cash_flags_absent"]=False
    elif mutation=="wrong_identity_class":x["security_bindings"]["XP"]["security_class"]="OTHER_COMMON"
    elif mutation=="duplicate_fact":x["fact_projections"].append(copy.deepcopy(x["fact_projections"][0]))
    else:
        x["fact_projections"][0]["payload"]["available_at_upper_bound"]="2023-09-11T14:00:00Z"
        refresh_fact(x)
    r=bind_cash_entitlements(**x)
    assert not r.removal_keys and len(r.remaining_unsupported_events)==len(x["unsupported_events"])
    if mutation in ("duplicate_fact","late_publication"):assert not r.events


@pytest.mark.parametrize("row_value",["0.58497",None,"nan","inf","0.58",True])
def test_r4_actual_vendor_row_must_match_top_amount_and_frozen_rate(row_value):
    x=_xp_precedence_case()
    classification=next(iter(x["cash_event_classification"].values()))
    classification["vendor_row"]["per_cash_div"]=row_value
    classification["classification_source_fingerprint"]=digest(
        {k:v for k,v in classification.items() if k!="classification_source_fingerprint"})
    assert classification["vendor_cash_per_raw_old_share"]==.58498
    r=bind_cash_entitlements(**x)
    assert not r.removal_keys and len(r.remaining_unsupported_events)==1


@pytest.mark.parametrize("record,expected,rule", [
    ("2024-05-24", "2024-05-23", "TPLUS2"),
    ("2024-05-28", "2024-05-24", "NYSE_T1_TRANSITION"),
    ("2024-05-29", "2024-05-29", "TPLUS1"),
])
def test_normal_ex_actual_nyse_transition_has_no_may28_ex(record, expected, rule):
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    days = pd.bdate_range("2024-05-20", "2024-06-03")
    days = days[days != pd.Timestamp("2024-05-27")]
    ex, key = normal_cash_ex_date(record, days, scope_end_exclusive="2026-01-01")
    assert str(ex.date()) == expected and key == rule


def test_legacy_binder_keeps_frozen_may28_coordinate_not_corrected_claim():
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    x = case(record="2024-05-28", pay="2024-06-01")
    ex, key = normal_cash_ex_date("2024-05-28", x["calendar"],
        scope_end_exclusive="2026-01-01", policy="FROZEN_PRE2026_LEGACY")
    assert str(ex.date()) == "2024-05-28" and key == "TPLUS1"
    assert bind_cash_entitlements(**x).events[0].ex_date == "2024-05-28"


def post_verified_ex_case():
    days = [str(d.date()) for d in pd.bdate_range("2026-02-20", "2026-03-02")]
    facts = dict(clock_role="POST_VERIFIED_ACCOUNTING_ONLY", available_at=None,
        ticker="AAA", security_id="FAKE_COMMON_SID", security_type="COMMON_STOCK",
        issuer_jurisdiction="US", pay_date_status="SOURCE_FIXED_ANNOUNCED_SCHEDULE",
        listing_identity="NYSE:AAA", identity_unique=True, currency="USD",
        issuer_source_fingerprint="5"*64, identity_source_fingerprint="6"*64,
        amount_unit=USD_PER_RAW_OLD_SHARE, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        ordinary_cash_confirmed=True, noncash_flags_absent=True,
        special_or_due_bill_indicator=False, late_notice_indicator=False,
        record_date="2026-02-27", pay_date="2026-03-30",
        publication_calendar_date="2026-02-11", vendor_ex_field="ex_div_date",
        vendor_exact_row_count=1,
        vendor_named_ex_date="2026-02-27", vendor_source_fingerprint="1"*64,
        cash_per_raw_share=.28, issuer_history_ex_dates=["2026-02-26"],
        prior_raw_close=dict(ticker="AAA",security_id="FAKE_COMMON_SID",
            trade_date="2026-02-26",raw_close=100.,price_coordinate="RAW_CLOSE",
            quantity_coordinate=RAW_OLD_SHARE_COORDINATE,source_fingerprint="2"*64))
    envelope=dict(path="FAKE_ONLY/post_verified.json",sha256=digest(facts),payload=facts)
    return dict(envelope=envelope,calendar=days,scope_end_exclusive="2027-01-01",
        calendar_binding=dict(status="SOURCE_BOUND_LEGAL_SESSION_CALENDAR",
            session_dates_sha256=digest(days),source_fingerprint="3"*64,
            source_reference="FAKE_ONLY/calendar.json"),
        rule_sources={"TPLUS1":dict(effective_from="2024-05-28",
            effective_until_exclusive=None,kind="FINRA_24_04_NORMAL_SMALL_CASH",source_fingerprint="4"*64,
            source_reference="FAKE_ONLY/NYSE_normal_rule.json")})


def test_post_verified_ex_preserves_conflict_unknown_clock_and_inputs():
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    x=post_verified_ex_case();before=copy.deepcopy(x)
    result=adjudicate_post_verified_cash_ex(**x)
    assert x==before and result["status"]=="ADJUDICATED_RESEARCH_EX_DATE"
    assert result["ex_date"]=="2026-02-27" and result["source_disagreement_preserved"]
    assert result["issuer_history_ex_dates"]==["2026-02-26"]
    assert result["available_at"] is None and not result["strict_PIT_promotion_eligible"]
    assert not result["production_qualified"] and not result["broker_payment_proven"]


@pytest.mark.parametrize("change", [
    "large", "noncash", "special", "late", "vendor", "field", "identity",
    "unit", "clock", "publication", "rule", "calendar", "raw_close",
    "adr", "foreign", "duplicate_calendar", "issuer_sha", "identity_sha",
    "vendor_sha", "row_count_bool", "row_count_duplicate", "placeholder_sid",
    "bool_amount", "inf_amount", "raw_unit", "missing_advance", "payload_guard",
    "foreign_issuer", "estimated_pay", "rule_kind", "rule_reference_type", "scope_ceiling",
])
def test_post_verified_ex_fails_closed_on_missing_or_exception_evidence(change):
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    x=post_verified_ex_case();f=x["envelope"]["payload"]
    if change=="large":f["cash_per_raw_share"]=25.
    elif change=="noncash":f["noncash_flags_absent"]=False
    elif change=="special":f["special_or_due_bill_indicator"]=True
    elif change=="late":f["late_notice_indicator"]=None
    elif change=="vendor":f["vendor_named_ex_date"]="2026-02-26"
    elif change=="field":f["vendor_ex_field"]="record_date"
    elif change=="identity":f["identity_unique"]=False
    elif change=="unit":f["quantity_coordinate"]="ADJUSTED_SHARES"
    elif change=="clock":f["available_at"]="2026-02-11T12:00:00Z"
    elif change=="publication":f["publication_calendar_date"]="2026-02-27"
    elif change=="rule":x["rule_sources"]["TPLUS1"]["effective_from"]="2024-05-29"
    elif change=="calendar":x["calendar"].remove("2026-02-26")
    elif change=="adr":f["security_type"]="AMERICAN_DEPOSITARY_SHARE"
    elif change=="foreign":f["currency"]="CAD"
    elif change=="duplicate_calendar":
        x["calendar"].append(x["calendar"][-1])
        x["calendar_binding"]["session_dates_sha256"]=digest(x["calendar"])
    elif change=="issuer_sha":f["issuer_source_fingerprint"]=""
    elif change=="identity_sha":f["identity_source_fingerprint"]=""
    elif change=="vendor_sha":f["vendor_source_fingerprint"]=""
    elif change=="row_count_bool":f["vendor_exact_row_count"]=True
    elif change=="row_count_duplicate":f["vendor_exact_row_count"]=2
    elif change=="placeholder_sid":f["security_id"]="UNKNOWN"
    elif change=="bool_amount":f["cash_per_raw_share"]=True
    elif change=="inf_amount":f["cash_per_raw_share"]=float("inf")
    elif change=="raw_unit":f["prior_raw_close"]["quantity_coordinate"]="ADJUSTED_SHARES"
    elif change=="missing_advance":f.pop("publication_calendar_date")
    elif change=="payload_guard":pass
    elif change=="foreign_issuer":f["issuer_jurisdiction"]="CA"
    elif change=="estimated_pay":f["pay_date_status"]="ON_OR_ABOUT"
    elif change=="rule_kind":x["rule_sources"]["TPLUS1"]["kind"]="UNKNOWN"
    elif change=="rule_reference_type":x["rule_sources"]["TPLUS1"]["source_reference"]=True
    elif change=="scope_ceiling":x["scope_end_exclusive"]="2028-01-01"
    else:f["prior_raw_close"]["raw_close"]=float("nan")
    x["envelope"]["sha256"]="f"*64 if change=="payload_guard" else digest(f)
    result=adjudicate_post_verified_cash_ex(**x)
    assert result["status"]=="BLOCKED_SOURCE" and result["reason"]
    assert result["available_at"] is None and not result["strict_PIT_promotion_eligible"]


def test_normal_ex_scope_and_historical_unknown_regime_fail_closed():
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    with pytest.raises(ValueError,match="RECORD_NOT_IN_FROZEN"):
        normal_cash_ex_date("2017-09-04",["2017-09-01","2017-09-04"],
                           scope_end_exclusive="2026-01-01")
    with pytest.raises(ValueError,match="LEGACY_EX_POLICY_PRE2026"):
        normal_cash_ex_date("2026-02-27",["2026-02-26","2026-02-27"],
            scope_end_exclusive="2027-01-01",policy="FROZEN_PRE2026_LEGACY")


@pytest.mark.parametrize("advance_days,expected", [(9,"BLOCKED_SOURCE"),(10,"ADJUDICATED_RESEARCH_EX_DATE")])
def test_post_verified_ex_advance_record_calendar_day_boundary(advance_days,expected):
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    x=post_verified_ex_case();facts=x["envelope"]["payload"]
    facts["publication_calendar_date"]=str((pd.Timestamp(facts["record_date"])-pd.Timedelta(days=advance_days)).date())
    x["envelope"]["sha256"]=digest(facts)
    assert adjudicate_post_verified_cash_ex(**x)["status"]==expected


@pytest.mark.parametrize("bad_day",["include_holiday","missing_may24"])
def test_nyse_transition_does_not_roll_using_bad_calendar(bad_day):
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    days=["2024-05-23","2024-05-24","2024-05-28","2024-05-29"]
    if bad_day=="include_holiday":days.insert(2,"2024-05-27")
    else:days.remove("2024-05-24")
    with pytest.raises(ValueError,match="NYSE_TRANSITION_CALENDAR"):
        normal_cash_ex_date("2024-05-28",days,scope_end_exclusive="2026-01-01")


def test_cash_source_adjudication_cannot_remove_independent_raw_quality_defect():
    import numpy as np
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    from scripts.research.a2.evaluation import joint_method_accounts as driver
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
    result=adjudicate_post_verified_cash_ex(**post_verified_ex_case())
    assert result["status"]=="ADJUDICATED_RESEARCH_EX_DATE" and "removal_keys" not in result
    prices=np.ones((2,1))
    market=MarketArrays(pd.to_datetime(["2026-02-26","2026-02-27"]),["AAA"],prices,prices)
    market.quality[1,0]=True  # Independent source raw defect, not event inheritance.
    projected=driver.with_effective_event_quality(market,{"unsupported_events":[]})
    assert projected.quality[1,0] and market.quality[1,0]
    assert not driver.legal_new_buy_domain(projected)[1,0]


def frozen_history_post_verified_case():
    x = post_verified_ex_case()
    days = [str(d.date()) for d in pd.bdate_range("2023-02-27", "2023-03-06")]
    x.update(calendar=days, scope_end_exclusive="2026-01-01",
             source_scope="FROZEN_PRE2026_NYSE_COMMON_USD")
    x["calendar_binding"]["session_dates_sha256"] = digest(days)
    x["rule_sources"] = {"TPLUS2": dict(effective_from="2017-09-05",
        effective_until_exclusive="2024-05-28", kind="FINRA_17_19_NORMAL_SMALL_CASH",
        source_fingerprint="4"*64, source_reference="FAKE_ONLY/normal_rule.json")}
    f = x["envelope"]["payload"]
    f.update(issuer_jurisdiction="CA", listed_exchange_jurisdiction="US",
        exchange_rule_applicability="NYSE_LISTED_RAW_USD_COMMON_SHARE",
        exchange_listing_source_reference="FAKE_ONLY/issuer_nyse_listing.pdf",
        exchange_listing_source_fingerprint="7"*64,
        record_date="2023-03-03", pay_date="2023-03-15",
        publication_calendar_date="2023-02-21", vendor_named_ex_date="2023-03-02",
        issuer_history_ex_dates=[])
    f["prior_raw_close"]["trade_date"] = "2023-03-01"
    x["envelope"]["sha256"] = digest(f)
    return x


def test_post_verified_frozen_history_explicit_scope_preserves_unknown_clock():
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    x = frozen_history_post_verified_case()
    before = copy.deepcopy(x)
    result = adjudicate_post_verified_cash_ex(**x)
    assert x == before and result["status"] == "ADJUDICATED_RESEARCH_EX_DATE"
    assert result["ex_date"] == "2023-03-02" and result["available_at"] is None
    assert not result["strict_PIT_promotion_eligible"] and not result["production_qualified"]
    x.pop("source_scope")
    assert adjudicate_post_verified_cash_ex(**x)["status"] == "BLOCKED_SOURCE"


@pytest.mark.parametrize("change", ["tsx", "cad", "listing_sha", "rule_basis", "missing_reference", "future", "unknown_scope", "noncash"])
def test_post_verified_frozen_history_does_not_borrow_wrong_venue_or_future_authority(change):
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    x = frozen_history_post_verified_case()
    f = x["envelope"]["payload"]
    if change == "tsx": f["listing_identity"] = "TSX:AAA"
    elif change == "cad": f["currency"] = "CAD"
    elif change == "listing_sha": f["exchange_listing_source_fingerprint"] = ""
    elif change == "rule_basis": f["exchange_rule_applicability"] = "CANADIAN_ISSUER_US_RULE_ASSUMED"
    elif change == "missing_reference": f.pop("exchange_listing_source_reference")
    elif change == "future": f["record_date"] = "2026-03-03"
    elif change == "unknown_scope": x["source_scope"] = "ANY_HISTORY"
    else: f["noncash_flags_absent"] = False
    x["envelope"]["sha256"] = digest(f)
    assert adjudicate_post_verified_cash_ex(**x)["status"] == "BLOCKED_SOURCE"


def historical_derived_event_case():
    x = frozen_history_post_verified_case()
    f = x["envelope"]["payload"]
    for key in ("vendor_exact_row_count", "vendor_ex_field", "vendor_named_ex_date", "vendor_source_fingerprint"):
        f.pop(key)
    key = dict(ticker="AAA", effective_date="2023-03-02",
        reason="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY",
        source_reference="FAKE_ONLY/original_catalogue.json", source_fingerprint="8"*64)
    f.update(ex_date_provenance_role="DERIVED_NYSE_NORMAL_EX_FROM_RECORD_DATE_MATCHED_EXACT_FROZEN_EVENT",
        exact_frozen_event_key=key, frozen_event_key_sha256=digest(key),
        frozen_event_exact_row_count=1, frozen_catalogue_source_fingerprint="9"*64)
    x["envelope"]["sha256"] = digest(f)
    return x


def test_historical_derived_ex_preserves_real_field_role_not_named_vendor():
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    x = historical_derived_event_case()
    before = copy.deepcopy(x)
    result = adjudicate_post_verified_cash_ex(**x)
    assert result["status"] == "ADJUDICATED_RESEARCH_EX_DATE" and x == before
    assert result["ex_date_provenance_role"].startswith("DERIVED_NYSE_NORMAL_EX")
    assert "vendor_named_ex_date" not in x["envelope"]["payload"]
    assert not result["exact_exchange_event_notice_obtained"]
    x.pop("source_scope")
    assert adjudicate_post_verified_cash_ex(**x)["status"] == "BLOCKED_SOURCE"


@pytest.mark.parametrize("change", ["date", "ticker", "share", "duplicate", "key_hash", "source_hash", "unknown_role"])
def test_historical_derived_event_cannot_waive_exact_coordinate_or_source(change):
    from scripts.research.a2.data.joint_cash_bindings import adjudicate_post_verified_cash_ex
    x = historical_derived_event_case()
    f = x["envelope"]["payload"]
    if change == "date": f["exact_frozen_event_key"]["effective_date"] = "2023-03-01"
    elif change == "ticker": f["exact_frozen_event_key"]["ticker"] = "BBB"
    elif change == "share": f["exact_frozen_event_key"]["reason"] = "UNSUPPORTED_AFFINE_CASH_OR_MIXED_VENDOR_TRANSFORM"
    elif change == "duplicate": f["frozen_event_exact_row_count"] = 2
    elif change == "key_hash": f["frozen_event_key_sha256"] = "0"*64
    elif change == "source_hash": f["frozen_catalogue_source_fingerprint"] = ""
    else: f["ex_date_provenance_role"] = "EFFECTIVE_DATE_RENAMED_VENDOR_EX"
    if change != "key_hash": f["frozen_event_key_sha256"] = digest(f["exact_frozen_event_key"])
    x["envelope"]["sha256"] = digest(f)
    assert adjudicate_post_verified_cash_ex(**x)["status"] == "BLOCKED_SOURCE"


def test_cboe_common_label_survives_complete_source_cash_binding():
    x = case(schema=2, record="2024-06-11", pay="2024-06-28")
    p = x["fact_projections"][0]["payload"]; p["listed_exchange"] = "CBOE"
    entry = x["security_bindings"]["AAA"]; entry["listing_identity"] = "CBOE:AAA"
    entry["security_id"] = source_derived_security_id(entry["issuer"], "AAA", entry["listing_identity"])
    entry["identity_payload_sha256"] = digest({k: entry[k] for k in ("security_id", "identity_kind", "issuer", "ticker", "listing_identity", "security_type")})
    x["pre_ex_raw_closes"]["AAA_FAKE"]["security_id"] = entry["security_id"]
    refresh_fact(x); before = copy.deepcopy(x); result = bind_cash_entitlements(**x)
    assert x == before and result.events and not result.remaining_unsupported_events
    assert result.proofs[0]["identity"]["identity"]["listing_identity"] == "CBOE:AAA"
    assert result.events[0].old_security_id != source_derived_security_id(entry["issuer"], "AAA", "NYSE:AAA")
    entry["listing_identity"] = "NYSE:AAA"
    entry["identity_payload_sha256"] = digest({k: entry[k] for k in ("security_id", "identity_kind", "issuer", "ticker", "listing_identity", "security_type")})
    assert not bind_cash_entitlements(**x).events


@pytest.mark.parametrize("listing,security_type", [
    ("CBOE:OTHER", "COMMON_STOCK"), ("BZX:AAA", "COMMON_STOCK"),
    ("Cboe:AAA", "COMMON_STOCK"), ("CBOE:AAA", "AMERICAN_DEPOSITARY_SHARE"),
    ("CBOE:AAA", "CLASS_B_COMMON_STOCK"), ("CBOE:AAA", "PREFERRED_STOCK"),
])
def test_cboe_source_label_does_not_guess_venue_ticker_or_share_class(listing, security_type):
    with pytest.raises(ValueError):
        source_derived_security_id("Alpha Inc.", "AAA", listing, security_type)


# Source-declared ex dates are research coordinates, not legal-calendar inserts.
def test_source_declared_ex_preserves_nontrading_record_and_old_policy_block():
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    days = ["2024-06-17", "2024-06-18", "2024-06-20", "2024-06-21"]
    for policy in ("NYSE_T1_TRANSITION_2024", "FROZEN_PRE2026_LEGACY"):
        with pytest.raises(ValueError, match="RECORD_NOT_IN_FROZEN_LEGAL_CALENDAR"):
            normal_cash_ex_date("2024-06-19", days, scope_end_exclusive="2026-01-01", policy=policy)
    ex, rule = normal_cash_ex_date("2024-06-19", days, scope_end_exclusive="2026-01-01",
        policy="SOURCE_DECLARED_EX_RESEARCH", source_declared_ex_date="2024-06-18")
    assert str(ex.date()) == "2024-06-18" and rule == "SOURCE_DECLARED_EX_RESEARCH"
    assert "2024-06-19" not in days


@pytest.mark.parametrize("value", [None, "2024-06-19", "2024-06-20", "2024-06-18T01:00:00", "2024-06-18T00:00:00Z", "2026-01-01"])
def test_source_declared_ex_rejects_missing_nontrading_future_or_after_record(value):
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    with pytest.raises(ValueError):
        normal_cash_ex_date("2024-06-19", ["2024-06-17", "2024-06-18", "2024-06-20"],
            scope_end_exclusive="2026-01-01", policy="SOURCE_DECLARED_EX_RESEARCH", source_declared_ex_date=value)


def test_source_declared_ex_requires_policy_and_consistency_for_trading_record():
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    days = ["2023-01-18", "2023-01-19", "2023-01-20"]
    with pytest.raises(ValueError, match="SOURCE_DECLARED_EX_POLICY_REQUIRED"):
        normal_cash_ex_date("2023-01-20", days, scope_end_exclusive="2026-01-01", source_declared_ex_date="2023-01-19")
    with pytest.raises(ValueError, match="CONFLICTS_WITH_NORMAL_TRADING_RECORD"):
        normal_cash_ex_date("2023-01-20", days, scope_end_exclusive="2026-01-01",
            policy="SOURCE_DECLARED_EX_RESEARCH", source_declared_ex_date="2023-01-18")
    assert normal_cash_ex_date("2023-01-20", days, scope_end_exclusive="2026-01-01",
        policy="SOURCE_DECLARED_EX_RESEARCH", source_declared_ex_date="2023-01-19")[0] == pd.Timestamp("2023-01-19")


def test_source_declared_ex_does_not_widen_pre2026_or_calendar_uniqueness():
    from scripts.research.a2.data.joint_cash_bindings import normal_cash_ex_date
    for days, end in [(["2024-06-18", "2024-06-18"], "2026-01-01"),
                      (["2024-06-20", "2024-06-18"], "2026-01-01"),
                      (["2024-06-18"], "2027-01-01")]:
        with pytest.raises(ValueError):
            normal_cash_ex_date("2024-06-19", days, scope_end_exclusive=end,
                policy="SOURCE_DECLARED_EX_RESEARCH", source_declared_ex_date="2024-06-18")
