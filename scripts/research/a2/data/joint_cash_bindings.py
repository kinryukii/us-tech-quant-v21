"""Caller-bound cash facts -> existing entitlement API, with explicit assumptions.

No files, market data, engine, account or fitted objects are read by this module.
The caller guards physical projection/calendar/vendor/identity/price bytes. This
adapter verifies payload bindings and returns a new catalogue and precise removal
keys. An expected normal-dividend ex/pay schedule is research input, not evidence
of a directly declared ex date, exchange receipt or broker payment. Explicit
ADS opt-in binds the separately declared per-ADS gross amount and class identity;
ordinary-share quantities, depositary fees and withholding are not inferred.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd
from scripts.v22.corporate_action_transition_r1 import (
    SourceBackedEntitlementEvent, RAW_OLD_SHARE_COORDINATE,
    USD_PER_RAW_OLD_SHARE, canonical_bytes, validate_closed_record_research_binding,
    CLOSED_RECORD_RESEARCH_POLICY, CLOSED_RECORD_RESEARCH_ROLE,
)

SPEC = {
    "calendar_end_exclusive": "2026-01-01",
    "small_cash_fraction_strict_upper_bound": 0.25,
    "ex_rule": "record prior legal market session before 2024-05-28; record session thereafter",
    "payment": "announced expected pay date may cross 2026; no future payment observation; first legal Open on/after schedule only if replay authorized",
    "availability": "caller explicit aware conservative publication upper bound; not exchange receipt proof",
    "same_share_coordinate": "amount and prior-session raw Close both per pre-ex RAW old common share",
    "removal": "exact ticker/effective_date/source_fingerprint key and explicit cash family only",
}


@dataclass(frozen=True)
class CashBindingResult:
    events: tuple[SourceBackedEntitlementEvent, ...]
    security_tickers: dict[str, str]
    source_binding: dict[str, Any]
    removal_keys: tuple[tuple[str, str, str], ...]
    remaining_unsupported_events: tuple[dict[str, Any], ...]
    proofs: tuple[dict[str, Any], ...]
    blocked: tuple[dict[str, Any], ...]


def _validate_explicit_total_base_variable_group(facts,binding,*,scope_end_exclusive):
    """Validate the new kind-profile; old annual/quarterly group gates stay intact."""
    from decimal import Decimal
    kinds=['QUARTERLY_BASE_COMMON_SHARE_CASH_DIVIDEND','QUARTERLY_VARIABLE_PERFORMANCE_BASED_COMMON_SHARE_CASH_DIVIDEND']
    identity=binding.get('frozen_account_identity_binding',{});row=identity.get('original_source_row',{});bridge=identity.get('exact_source_common_class_binding',{})
    expected=dict(security_id=facts.get('security_id'),ticker=facts.get('ticker'),listing_identity=facts.get('listing_identity'),currency='USD',cash_per_raw_share=facts.get('cash_per_raw_share'),record_date=facts.get('record_date'),pay_date=facts.get('pay_date'),ex_date=facts['exact_frozen_event_key']['effective_date'],publication_calendar_date=facts.get('publication_calendar_date'))
    if (pd.Timestamp(scope_end_exclusive)!=pd.Timestamp('2026-01-01') or not pd.Timestamp('2023-01-01')<=pd.Timestamp(facts['record_date'])<pd.Timestamp('2026-01-01')
        or facts.get('issuer_jurisdiction')!='US' or facts.get('ordinary_cash_confirmed') is not False or facts.get('common_cash_component_group_confirmed') is not True
        or binding.get('status')!='PINNED_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP'
        or binding.get('cash_evidence_role')!='SOURCE_BOUND_EXPLICIT_TOTAL_BASE_AND_VARIABLE_COMMON_CASH_COMPONENT_GROUP'
        or binding.get('amount_aggregation_role')!='EXPLICIT_ORIGINAL_TOTAL_EQUALS_TWO_DECIMAL_COMPONENTS_CREDIT_ONCE'
        or binding.get('clock_applicability_role')!='EXPLICIT_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION'
        or binding.get('consumption_set_role')!='ORDINARY_PAY_END_CLOCK_SET_PLUS_EXPLICIT_SAME_CLOCK_COMPONENT_GROUPS'
        or binding.get('accounting_clock_convention')!='ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION'
        or binding.get('annual_ordinary_or_quarterly_reclassification') is not False or binding.get('available_at') is not None
        or binding.get('actual_SEC_filed_date')!=facts.get('publication_calendar_date')
        or any(binding.get(k)!='UNKNOWN' for k in ('historical_availability_authority','exchange_notice_authority','actual_exchange_ex_authority'))
        or any(binding.get(k) is not False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV','issuer_name_alias_used'))
        or any(binding.get(k)!=v for k,v in expected.items()) or binding.get('original_exact_key')!=facts['exact_frozen_event_key']
        or identity.get('available_at') is not None or identity.get('legal_identity_authority_granted') is not False or identity.get('historical_availability_qualified') is not False
        or identity.get('identity_clock_role')!='ORIGINAL_FROZEN_EFFECTIVE_INTERVAL_NOT_PUBLICATION'
        or identity.get('identity',{}).get('security_id')!=facts['security_id']
        or row.get('security_id_type')!='CUSIP' or row.get('cusip')!=row.get('security_id') or row.get('ticker')!=facts['ticker'] or row.get('moomoo_transport_code')!='US.'+facts['ticker']
        or bridge.get('status')!='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT' or bridge.get('source_CUSIP')!=row.get('cusip')
        or bridge.get('source_common_class_literal')!='Common Stock' or bridge.get('original_frozen_class_literal')!=row.get('title_of_class')
        or bridge.get('no_class_alias') is not True or bridge.get('original_frozen_class_rewritten') is not False):
        raise ValueError('BASE_VARIABLE_GROUP_EXACT_SOURCE_COMMON_UNIT_IDENTITY_AND_CLOCK_REQUIRED')
    parts=binding.get('cash_components')
    if not isinstance(parts,list) or len(parts)!=2 or [x.get('component_kind') for x in parts]!=kinds or parts[0].get('independent_component_fact_ref')==parts[1].get('independent_component_fact_ref'):
        raise ValueError('BASE_VARIABLE_GROUP_TWO_DISTINCT_SOURCE_COMPONENTS_REQUIRED')
    for part in parts:
        if (not re.fullmatch(r'[0-9]+[.][0-9]+',str(part.get('source_amount_literal'))) or Decimal(part['source_amount_literal'])<=0 or part.get('component_is_not_separate_account_credit') is not True
            or not part.get('source_component_literal') or part.get('amount_unit')!=USD_PER_RAW_OLD_SHARE or part.get('quantity_coordinate')!=RAW_OLD_SHARE_COORDINATE
            or any(part.get(k)!=expected[k] for k in ('security_id','ticker','currency','record_date','pay_date','ex_date'))):raise ValueError('BASE_VARIABLE_GROUP_INDEPENDENT_COMPONENT_UNIT_CLOCK_REQUIRED')
    total=Decimal(binding['total_cash_amount_literal'])
    if total<=0 or total!=sum((Decimal(x['source_amount_literal']) for x in parts),Decimal(0)) or float(total)!=facts['cash_per_raw_share'] or binding.get('group_id')!=_hash(dict(components=parts,original_key=facts['exact_frozen_event_key'])):
        raise ValueError('BASE_VARIABLE_GROUP_EXPLICIT_TOTAL_AND_SINGLE_CREDIT_REQUIRED')
    for name in ('component_group_source_ref','original_source_custody_ref','original_cash_fragment_ref','original_cash_text_ref','original_full_HTTP_ref','same_file_cash_identity_support_ref','source_common_CUSIP_identity_custody_ref'):
        ref=binding.get(name)
        if not isinstance(ref,dict) or not re.match(r'^D:[/\\]',str(ref.get('path'))):raise ValueError('BASE_VARIABLE_GROUP_PHYSICAL_SOURCE_REF_REQUIRED')
        _sha(ref.get('sha256'),'base_variable_'+name)
    capture=pd.Timestamp(binding['current_capture_utc'])
    if pd.isna(capture) or capture.tzinfo is None or capture<pd.Timestamp(binding['publication_calendar_date']).tz_localize('UTC') or pd.Timestamp(binding['source_company_declaration_date'])>pd.Timestamp(binding['publication_calendar_date']) or binding.get('private_board_declaration_date') is not None:
        raise ValueError('BASE_VARIABLE_GROUP_ACTUAL_FILED_CAPTURE_AND_UNKNOWN_PRIVATE_CLOCK_REQUIRED')


def _hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("MISSING_SHA256:" + field)
    return value.lower()



def validate_source_precedence_policy(envelope):
    """Explicit XP-only declared-gross research policy, not numeric reconciliation."""
    if envelope is None:
        return None
    payload, guard = _guard(envelope)
    if envelope.get("payload_sha256") != _hash(payload):
        raise ValueError("SOURCE_PRECEDENCE_CANONICAL_PAYLOAD_CHANGED")
    expected = dict(schema_version=1, policy_id="XP_2023_09_11_SOURCE_DECLARED_GROSS_R4",
                    stage="continuation/cash_r4", accounting_authority="SOURCE_DECLARED_GROSS",
                    numeric_conflict="RETAIN_UNRECONCILED_VENDOR_DIAGNOSTIC")
    if (set(payload) != set(expected) | {"scope"}
            or any(payload.get(k) != v for k,v in expected.items())
            or type(payload["schema_version"]) is not int):
        raise ValueError("SOURCE_PRECEDENCE_POLICY_SCOPE_CHANGED")
    scope = payload["scope"]
    fixed = dict(ticker="XP", effective_date="2023-09-11", security_class="CLASS_A_COMMON_SHARES",
                 security_type="COMMON_STOCK", listing_identity="NASDAQ:XP",
                 amount_unit=USD_PER_RAW_OLD_SHARE, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
                 issuer_cash_per_raw_old_share=.58, vendor_cash_per_raw_old_share=.58498,
                 vendor_cash_field="per_cash_div", non_cash_flags_absent=True)
    hashes = ("vendor_event_source_fingerprint", "original_statement_source_sha256",
              "statement_fact_sha256", "statement_payload_sha256", "identity_payload_sha256",
              "vendor_typed_cash_field_source_sha256")
    if (not isinstance(scope, dict) or set(scope) != set(fixed) | set(hashes) | {"fact_key","security_id"}
            or any(scope.get(k) != v for k,v in fixed.items())
            or scope.get("non_cash_flags_absent") is not True):
        raise ValueError("SOURCE_PRECEDENCE_FIXED_BINDINGS_CHANGED")
    for k in ("issuer_cash_per_raw_old_share","vendor_cash_per_raw_old_share"):
        if isinstance(scope[k],bool) or not isinstance(scope[k],(int,float)) or not math.isfinite(scope[k]):
            raise ValueError("SOURCE_PRECEDENCE_CASH_VALUE_INVALID")
    for k in hashes:_sha(scope.get(k), "source_precedence_"+k)
    for k in ("fact_key","security_id"):
        if not isinstance(scope[k],str) or not scope[k] or scope[k]!=scope[k].strip():
            raise ValueError("SOURCE_PRECEDENCE_IDENTITY_REQUIRED")
    return dict(payload=copy.deepcopy(payload), guard=guard,
                qualification_basis="SOURCE_DECLARED_GROSS",
                vendor_numeric_conflict_reconciled=False, final_paid_rate_verified=False)


def _source_precedence_matches(policy, event, proof, classification, identity, item):
    scope=policy["payload"]["scope"];fact=proof.get("source_precedence_fact",{})
    actual=dict(ticker=event.ticker,effective_date=event.ex_date,fact_key=proof["fact_key"],
        vendor_event_source_fingerprint=item["source_fingerprint"],
        original_statement_source_sha256=fact.get("original_statement_source_sha256"),
        statement_fact_sha256=event.source_fingerprint,
        statement_payload_sha256=proof["projection"]["payload_sha256"],
        security_id=event.old_security_id,security_class=fact.get("security_class"),
        security_type=identity.get("security_type"),listing_identity=identity.get("listing_identity"),
        identity_payload_sha256=identity.get("identity_payload_sha256"),
        amount_unit=event.amount_unit,quantity_coordinate=event.quantity_coordinate,
        issuer_cash_per_raw_old_share=event.cash_per_old_share,
        vendor_cash_per_raw_old_share=classification.get("vendor_cash_per_raw_old_share"),
        vendor_typed_cash_field_source_sha256=classification.get("vendor_typed_cash_field_source_sha256"),
        vendor_cash_field=classification.get("vendor_cash_field"),
        non_cash_flags_absent=classification.get("non_cash_flags_absent"))
    if (actual!=scope or identity.get("security_class")!="CLASS_A_COMMON_SHARES"
            or classification.get("original_statement_source_sha256")!=scope["original_statement_source_sha256"]
            or classification.get("non_cash_flags_absent") is not True
            or item.get("reason")!="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY"):
        return False
    row=classification.get("vendor_row")
    if not isinstance(row,dict):return False
    raw=row.get(scope["vendor_cash_field"])
    if isinstance(raw,bool):return False
    try:row_amount=float(raw)
    except (TypeError,ValueError,OverflowError):return False
    if (not math.isfinite(row_amount) or row_amount!=scope["vendor_cash_per_raw_old_share"]
            or row_amount!=classification.get("vendor_cash_per_raw_old_share")):
        return False
    body={k:v for k,v in classification.items() if k!="classification_source_fingerprint"}
    return classification.get("classification_source_fingerprint")==_hash(body)


def _day(value, field, *, known_future_schedule=False):
    try:
        day = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_DATE:" + field) from exc
    if pd.isna(day) or day.tzinfo is not None or day != day.normalize():
        raise ValueError("INVALID_DATE:" + field)
    if not known_future_schedule and day >= pd.Timestamp(SPEC["calendar_end_exclusive"]):
        raise ValueError("TEST_CONTENT_FORBIDDEN:" + field)
    return day


def _aware(value, field):
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_AVAILABLE_AT:" + field) from exc
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("INVALID_AVAILABLE_AT:" + field)
    stamp = stamp.tz_convert("UTC")
    if stamp >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise ValueError("TEST_CONTENT_FORBIDDEN:" + field)
    return stamp


def _clock(day, hour, minute=0):
    return (day + pd.Timedelta(hours=hour, minutes=minute)).tz_localize("America/New_York").tz_convert("UTC")


def source_derived_security_id(issuer, ticker, listing_identity, security_type="COMMON_STOCK"):
    """Stable identity ontology, independent of announcement/revision hashes."""
    values = (issuer, ticker, listing_identity)
    if any(not isinstance(x, str) or not x.strip() or x != x.strip() for x in values):
        raise ValueError("INVALID_IDENTITY_ONTOLOGY")
    # CBOE is the exact source market label, not an invented BZX legal venue.
    # Namespace identity grants no PIT, listing, tax or account authority.
    labels = ("NYSE:" + ticker, "NASDAQ:" + ticker, "NYSE_AMERICAN:" + ticker)
    if security_type == "COMMON_STOCK":
        labels += ("CBOE:" + ticker,)
    if listing_identity not in labels:
        raise ValueError("UNSUPPORTED_OR_MISMATCHED_LISTING_IDENTITY")
    if security_type not in ("COMMON_STOCK", "AMERICAN_DEPOSITARY_SHARE"):
        raise ValueError("UNSUPPORTED_SECURITY_CLASS_ONTOLOGY")
    prefix = "SOURCE_ISSUER_ADS_CLASS:" if security_type == "AMERICAN_DEPOSITARY_SHARE" else "SOURCE_ISSUER_COMMON_CLASS:"
    return prefix + _hash({"issuer": issuer, "venue": listing_identity.split(":")[0], "common_class": security_type})


def _guard(envelope):
    payload = envelope["payload"]
    fingerprint = _hash(payload)
    physical_sha = _sha(envelope["sha256"], "fact_projection")
    path = envelope["path"]
    if not isinstance(path, str) or not path:
        raise ValueError("FACT_PROJECTION_PATH_REQUIRED")
    guard = envelope.get("guard")
    if physical_sha == fingerprint:
        mode = "CANONICAL_PAYLOAD_BYTES_SHA_MATCH"
    elif (isinstance(guard, dict) and guard.get("status") == "HASH_VERIFIED_PAYLOAD"
          and guard.get("path") == path and guard.get("sha256") == envelope["sha256"]
          and guard.get("payload_sha256") == fingerprint):
        mode = "CALLER_PHYSICAL_BYTES_GUARD_DECLARATION"
    else:
        raise ValueError("UNBOUND_FACT_PAYLOAD")
    return payload, {"path": path, "sha256": physical_sha, "payload_sha256": fingerprint,
                     "binding_mode": mode, "physical_bytes_read_by_binder": False}


def _rules(rule_sources):
    expected = {
        "TPLUS2": {"effective_from": "2017-09-05", "effective_until_exclusive": "2024-05-28", "kind": "FINRA_17_19_NORMAL_SMALL_CASH"},
        "TPLUS1": {"effective_from": "2024-05-28", "kind": "FINRA_24_04_NORMAL_SMALL_CASH"},
    }
    if set(rule_sources) != set(expected):
        raise ValueError("EX_RULE_SET_NOT_FROZEN")
    for name, fixed in expected.items():
        rule = rule_sources[name]
        if any(rule.get(k) != v for k, v in fixed.items()):
            raise ValueError("EX_RULE_INTERVAL_OR_KIND_CHANGED:" + name)
        if name == "TPLUS1" and rule.get("effective_until_exclusive") not in (None, "2026-01-01"):
            raise ValueError("EX_RULE_INTERVAL_CHANGED:TPLUS1")
        _sha(rule.get("source_fingerprint"), "ex_rule")
        if not isinstance(rule.get("source_reference"), str) or not rule["source_reference"]:
            raise ValueError("EX_RULE_SOURCE_REFERENCE_REQUIRED")
    return copy.deepcopy(rule_sources)


# The frozen binder below deliberately keeps its original May-28 boundary.
# New source adjudications use the exchange's one-session transition exception.
# Neither date policy grants access to a market/test window or source authority.
NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH = "NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH"
NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH = "NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH"


NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH = "NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH"
NSCC_CNS_RECORD_RESEARCH_ROLE = "NSCC_CNS_PROJECTED_RECORD_T1_FROZEN_RESEARCH_COORDINATE"
NSCC_CNS_2025_NOTICE_SHA256 = "90607850a1cb000ea9c734ab02f74af0b8b45daf87ef84a1df1b441116ab996a"
NSCC_CNS_2025_SECTION_SHA256 = "829f987ac599ed96f03b4979a867039b5906f29580a6221dde7316ef5840dc4d"


def validate_cns_bank_holiday_record_binding(binding, *, calendar, record_date,
                                            scope_end_exclusive, facts=None):
    """Pinned NSCC processing projection; issuer record and exchange authority stay.

    The source owner must physically pin both original notice and exact extracted
    section. This pure validator checks their identities and caller-bound facts;
    the all-securities notice creates no direct exchange-ex or availability fact.
    """
    sessions=tuple(pd.Timestamp(day) for day in calendar)
    if (pd.Timestamp(scope_end_exclusive)!=pd.Timestamp("2026-01-01")
            or not isinstance(binding,dict)
            or binding.get("policy_id")!=NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH
            or binding.get("status")!="PINNED_NSCC_CNS_BANK_HOLIDAY_RECORD_PROJECTION"
            or binding.get("record_projection_role")!="ALL_SECURITIES_PUBLISHED_RECORD_DATE_NSCC_CNS_RESEARCH_ONLY"
            or binding.get("published_record_date")!=record_date
            or record_date!="2025-11-11" or binding.get("cns_projected_record_date")!="2025-11-10"
            or binding.get("notice_number")!="a9648" or binding.get("notice_publication_date")!="2025-10-02"
            or binding.get("notice_section")!="CNS Dividend Processing"
            or type(binding.get("notice_page_zero_based")) is not int or binding["notice_page_zero_based"]!=1
            or binding.get("notice_primary_url")!="https://www.dtcc.com/-/media/Files/pdf/2025/10/2/a9648.pdf"
            or binding.get("actual_capture_url")!="https://files.dtcc.com/download/assets/a9648/5d1b3be0ceb411f08977de3dd66d09b0"
            or binding.get("published_record_preserved") is not True
            or binding.get("cns_settlement_on_published_record_date") is not False
            or binding.get("cns_closing_positions_identical") is not True
            or binding.get("market_session_on_published_record_date") is not True
            or binding.get("source_declared_ex_date") is not None
            or binding.get("independent_actual_ex_date") is not None or binding.get("available_at") is not None
            or any(binding.get(k)!="UNKNOWN" for k in ("historical_availability_authority","exchange_notice_authority","actual_exchange_ex_authority"))
            or any(binding.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
        raise ValueError("NSCC_CNS_EXPLICIT_PRE2026_RECORD_PROJECTION_REQUIRED")
    record=pd.Timestamp(record_date);projected=pd.Timestamp(binding["cns_projected_record_date"])
    cb=binding.get("calendar_binding",{})
    if (not sessions or tuple(sorted(set(sessions)))!=sessions
            or any(pd.isna(day) or day.tzinfo is not None or day!=day.normalize()
                   or day>=pd.Timestamp(scope_end_exclusive) for day in sessions)
            or record not in sessions or projected not in sessions
            or sessions.index(record)==0 or sessions[sessions.index(record)-1]!=projected
            or not isinstance(cb,dict) or cb.get("status")!="SOURCE_BOUND_LEGAL_SESSION_CALENDAR"
            or cb.get("session_dates_sha256")!=_hash([str(day.date()) for day in sessions])
            or not isinstance(cb.get("source_reference"),str) or not cb["source_reference"].strip()):
        raise ValueError("NSCC_CNS_COMPLETE_ORIGINAL_TRADING_CALENDAR_REQUIRED")
    _sha(cb.get("source_fingerprint"),"NSCC_CNS_calendar")
    for name in ("notice_source_ref","notice_section_ref","issuer_record_source_ref","security_identity_source_ref"):
        ref=binding.get(name)
        if (not isinstance(ref,dict) or set(ref)!={"path","sha256"}
                or not isinstance(ref.get("path"),str) or not re.match(r"^D:[/\\]",ref["path"])):
            raise ValueError("NSCC_CNS_PINNED_SOURCE_REF_REQUIRED:"+name)
        _sha(ref["sha256"],"NSCC_CNS_"+name)
    if (binding["notice_source_ref"]["sha256"]!=NSCC_CNS_2025_NOTICE_SHA256
            or binding["notice_section_ref"]["sha256"]!=NSCC_CNS_2025_SECTION_SHA256
            or binding.get("notice_section_source_sha256")!=NSCC_CNS_2025_NOTICE_SHA256):
        raise ValueError("NSCC_CNS_EXACT_ORIGINAL_NOTICE_AND_SECTION_REQUIRED")
    key=binding.get("exact_original_frozen_event_key",{})
    if (not isinstance(key,dict) or set(key)!={"ticker","effective_date","reason","source_reference","source_fingerprint"}
            or key.get("effective_date")!=str(projected.date())
            or key.get("reason")!="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY"
            or not isinstance(binding.get("ticker"),str) or not binding["ticker"].strip()
            or key.get("ticker")!=binding["ticker"]
            or not isinstance(binding.get("security_id"),str) or binding["security_id"] in ("","UNKNOWN")
            or binding.get("listing_identity") not in ("NYSE:"+binding["ticker"],"NASDAQ:"+binding["ticker"],"CBOE:"+binding["ticker"])
            or not isinstance(key.get("source_reference"),str) or not key["source_reference"].strip()
            or binding.get("ex_date")!=str(projected.date())):
        raise ValueError("NSCC_CNS_EXACT_FROZEN_SECURITY_AND_EVENT_REQUIRED")
    _sha(key.get("source_fingerprint"),"NSCC_CNS_original_event")
    pay=_day(binding.get("pay_date"),"NSCC_CNS_fixed_pay",known_future_schedule=True)
    if pay<record:raise ValueError("NSCC_CNS_FIXED_PAYMENT_BEFORE_PUBLISHED_RECORD")
    if facts is not None:
        if not isinstance(facts,dict):raise ValueError("NSCC_CNS_TYPED_FACTS_REQUIRED")
        exact=dict(ticker=facts.get("ticker"),security_id=facts.get("security_id"),
            listing_identity=facts.get("listing_identity"),pay_date=facts.get("pay_date"))
        if (any(binding.get(k)!=v for k,v in exact.items())
                or binding["exact_original_frozen_event_key"]!=facts.get("exact_frozen_event_key")
                or binding["issuer_record_source_ref"]["sha256"]!=facts.get("issuer_source_fingerprint")
                or binding["security_identity_source_ref"]["sha256"]!=facts.get("identity_source_fingerprint")
                or facts.get("ex_date_provenance_role")!=NSCC_CNS_RECORD_RESEARCH_ROLE):
            raise ValueError("NSCC_CNS_SAME_ISSUER_IDENTITY_AND_FROZEN_KEY_REQUIRED")
    return projected


def normal_cash_ex_date(record, calendar, *, scope_end_exclusive,
                        policy="NYSE_T1_TRANSITION_2024", source_declared_ex_date=None,
                        nyse_nonbusiness_record_binding=None, closed_record_research_binding=None,
                        nyse_post_t1_nonbusiness_record_binding=None, cns_bank_holiday_record_binding=None):
    """Pure normal-small-cash date coordinate; caller supplies source authority."""
    end = pd.Timestamp(scope_end_exclusive)
    record = pd.Timestamp(record)
    sessions = tuple(pd.Timestamp(day) for day in calendar)
    if (pd.isna(end) or end.tzinfo is not None or end != end.normalize()
            or pd.isna(record) or record.tzinfo is not None or record != record.normalize()
            or any(pd.isna(day) or day.tzinfo is not None or day != day.normalize()
                   or day >= end for day in sessions)):
        raise ValueError("EX_DATE_SCOPE_OR_CALENDAR_INVALID")
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("LEGAL_CALENDAR_UNIQUE_SORTED_REQUIRED")
    if record >= end:
        raise ValueError("EX_DATE_OUTSIDE_EXPLICIT_SOURCE_SCOPE")
    if policy==NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH:
        if (source_declared_ex_date is not None or nyse_nonbusiness_record_binding is not None
                or closed_record_research_binding is not None or nyse_post_t1_nonbusiness_record_binding is not None):
            raise ValueError("NSCC_CNS_EXCLUSIVE_EXPLICIT_POLICY_REQUIRED")
        projected=validate_cns_bank_holiday_record_binding(cns_bank_holiday_record_binding,
            calendar=sessions,record_date=str(record.date()),scope_end_exclusive=scope_end_exclusive)
        return normal_cash_ex_date(projected,sessions,scope_end_exclusive=scope_end_exclusive,
            policy="NYSE_T1_TRANSITION_2024")
    if cns_bank_holiday_record_binding is not None:
        raise ValueError("NSCC_CNS_EXPLICIT_POLICY_REQUIRED")
    if policy==NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH:
        binding=nyse_post_t1_nonbusiness_record_binding
        if (end!=pd.Timestamp("2026-01-01") or source_declared_ex_date is not None
                or nyse_nonbusiness_record_binding is not None or closed_record_research_binding is not None
                or not isinstance(binding,dict) or binding.get("status")!="PINNED_NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH_COORDINATE"
                or binding.get("policy_id")!=policy or binding.get("record_date")!=str(record.date())
                or binding.get("record_from_inclusive")!="2024-05-29"
                or binding.get("actual_exchange_ex_authority")!="UNKNOWN"
                or binding.get("exchange_notice_authority")!="UNKNOWN"
                or binding.get("historical_availability_authority")!="UNKNOWN"
                or binding.get("source_declared_ex_date") is not None
                or any(binding.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                or record<pd.Timestamp("2024-05-29") or record in sessions or not sessions[0]<record<sessions[-1]):
            raise ValueError("NYSE_POST_T1_NONBUSINESS_EXPLICIT_RESEARCH_BINDING_REQUIRED")
        calendar_source=binding.get("calendar_binding",{})
        if (calendar_source.get("status")!="SOURCE_BOUND_LEGAL_SESSION_CALENDAR"
                or calendar_source.get("session_dates_sha256")!=_hash([str(d.date()) for d in sessions])
                or not calendar_source.get("source_reference")
                or binding.get("calendar_role")!="ORIGINAL_FROZEN_RESEARCH_SESSIONS_NOT_INDEPENDENT_NYSE_CERTIFIED_CALENDAR"):
            raise ValueError("NYSE_POST_T1_COMPLETE_ORIGINAL_CALENDAR_REQUIRED")
        _sha(calendar_source.get("source_fingerprint"),"NYSE_post_T1_calendar")
        for key in ("rule_source_ref","original_rule_pdf_ref","accepted_original_rule_source_ref"):
            ref=binding.get(key,{})
            if set(ref)!={"path","sha256"} or not ref.get("path"):raise ValueError("NYSE_POST_T1_ORIGINAL_RULE_REF_REQUIRED")
            _sha(ref["sha256"],"NYSE_post_T1_rule")
        if binding.get("necessary_rule_page_indices")!=[5,7,21,23]:
            raise ValueError("NYSE_POST_T1_EFFECTIVE_REDLINED_RULE_PAGES_REQUIRED")
        prior=[day for day in sessions if day<record];ex=prior[-1]
        key=binding.get("exact_original_frozen_event_key",{})
        if (set(key)!={"ticker","effective_date","reason","source_reference","source_fingerprint"}
                or key.get("effective_date")!=str(ex.date()) or key.get("reason")!="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY"
                or not key.get("ticker") or not key.get("source_reference")):
            raise ValueError("NYSE_POST_T1_EXACT_FROZEN_EVENT_COORDINATE_REQUIRED")
        _sha(key.get("source_fingerprint"),"NYSE_post_T1_original_key")
        return ex,"TPLUS1"
    if nyse_post_t1_nonbusiness_record_binding is not None:
        raise ValueError("NYSE_POST_T1_EXPLICIT_POLICY_REQUIRED")
    if policy==CLOSED_RECORD_RESEARCH_POLICY:
        if (end!=pd.Timestamp("2026-01-01") or source_declared_ex_date is not None
                or nyse_nonbusiness_record_binding is not None):
            raise ValueError("CLOSED_RECORD_EXPLICIT_PRE2026_POLICY_REQUIRED")
        ex=validate_closed_record_research_binding(closed_record_research_binding,
            calendar=sessions,record_date=str(record.date()))
        return ex,CLOSED_RECORD_RESEARCH_POLICY
    if closed_record_research_binding is not None:
        raise ValueError("CLOSED_RECORD_EXPLICIT_POLICY_REQUIRED")
    if policy == NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH:
        binding=nyse_nonbusiness_record_binding
        if (end>pd.Timestamp("2026-01-01") or source_declared_ex_date is not None
                or not isinstance(binding,dict)
                or binding.get("status")!="PINNED_NYSE_RULE235_PRE_T1_NONBUSINESS_COORDINATE"
                or binding.get("policy_id")!=policy
                or binding.get("record_date")!=str(record.date())
                or binding.get("record_before_exclusive")!="2024-05-28"
                or binding.get("exchange_notice_authority")!="UNKNOWN"
                or binding.get("actual_exchange_ex_authority")!="UNKNOWN"
                or binding.get("strict_PIT") is not False):
            raise ValueError("NYSE_PRE_T1_NONBUSINESS_SOURCE_BINDING_REQUIRED")
        cb=binding.get("calendar_binding",{})
        if (cb.get("status")!="SOURCE_BOUND_LEGAL_SESSION_CALENDAR"
                or cb.get("session_dates_sha256")!=_hash([str(d.date()) for d in sessions])
                or not cb.get("source_reference")):
            raise ValueError("NYSE_NONBUSINESS_COMPLETE_CALENDAR_BINDING_REQUIRED")
        _sha(cb.get("source_fingerprint"),"NYSE_nonbusiness_calendar")
        for ref in (binding.get("rule_source_ref"),binding.get("original_rule_pdf_ref")):
            if not isinstance(ref,dict) or set(ref)!={"path","sha256"} or not ref.get("path"):
                raise ValueError("NYSE_NONBUSINESS_ORIGINAL_RULE_REF_REQUIRED")
            _sha(ref["sha256"],"NYSE_nonbusiness_rule")
        pages=binding.get("necessary_rule_pages")
        if (not isinstance(pages,list) or [p.get("page_zero_based") for p in pages]!=[3,23]):
            raise ValueError("NYSE_NONBUSINESS_EXACT_RULE_PAGES_REQUIRED")
        for page in pages:
            _sha(page.get("original_extract_text_sha256"),"NYSE_nonbusiness_rule_page")
            _sha(page.get("text_ref",{}).get("sha256"),"NYSE_nonbusiness_saved_rule_page")
        if record>=pd.Timestamp("2024-05-28"):
            raise ValueError("NYSE_NONBUSINESS_POST_T1_EFFECTIVE_SOURCE_UNBOUND")
        if record in sessions:
            return normal_cash_ex_date(record,sessions,scope_end_exclusive=scope_end_exclusive)
        if record<pd.Timestamp("2017-09-05") or not sessions[0]<record<sessions[-1]:
            raise ValueError("NYSE_NONBUSINESS_RECORD_OUTSIDE_COMPLETE_CALENDAR")
        prior=[day for day in sessions if day<record]
        if len(prior)<2:
            raise ValueError("NYSE_NONBUSINESS_SECOND_PRIOR_SESSION_MISSING")
        return prior[-2],"TPLUS2"
    if nyse_nonbusiness_record_binding is not None:
        raise ValueError("NYSE_NONBUSINESS_EXPLICIT_POLICY_REQUIRED")
    if policy == "SOURCE_DECLARED_EX_RESEARCH":
        # A source-declared date is a coordinate, never a calendar repair or
        # an inferred UPC designation. Default frozen policies remain below.
        if end > pd.Timestamp("2026-01-01") or source_declared_ex_date is None:
            raise ValueError("EXACT_PRE2026_SOURCE_DECLARED_EX_REQUIRED")
        ex = pd.Timestamp(source_declared_ex_date)
        if (pd.isna(ex) or ex.tzinfo is not None or ex != ex.normalize()
                or ex not in sessions or ex >= end or ex > record
                or record < pd.Timestamp("2017-09-05")):
            raise ValueError("SOURCE_DECLARED_EX_COORDINATE_INVALID")
        if record in sessions:
            expected, _ = normal_cash_ex_date(record, sessions,
                scope_end_exclusive=scope_end_exclusive,
                policy="NYSE_T1_TRANSITION_2024")
            if ex != expected:
                raise ValueError("SOURCE_DECLARED_EX_CONFLICTS_WITH_NORMAL_TRADING_RECORD")
        return ex, "SOURCE_DECLARED_EX_RESEARCH"
    if source_declared_ex_date is not None:
        raise ValueError("SOURCE_DECLARED_EX_POLICY_REQUIRED")
    if record not in sessions or record < pd.Timestamp("2017-09-05"):
        raise ValueError("RECORD_NOT_IN_FROZEN_LEGAL_CALENDAR")
    if policy not in ("FROZEN_PRE2026_LEGACY", "NYSE_T1_TRANSITION_2024"):
        raise ValueError("EX_DATE_POLICY_UNKNOWN")
    if policy == "FROZEN_PRE2026_LEGACY" and end > pd.Timestamp("2026-01-01"):
        raise ValueError("LEGACY_EX_POLICY_PRE2026_ONLY")
    transition = record == pd.Timestamp("2024-05-28")
    prior_record = record < pd.Timestamp("2024-05-28") or (
        transition and policy == "NYSE_T1_TRANSITION_2024")
    if prior_record:
        pos = sessions.index(record)
        if pos == 0:
            raise ValueError("PRIOR_RECORD_SESSION_MISSING")
        if transition and sessions[pos-1] != pd.Timestamp("2024-05-24"):
            raise ValueError("NYSE_TRANSITION_CALENDAR_UNSUPPORTED")
        return sessions[pos-1], ("NYSE_T1_TRANSITION" if transition else "TPLUS2")
    return record, "TPLUS1"


def adjudicate_post_verified_cash_ex(envelope, *, calendar, calendar_binding,
                                     rule_sources, scope_end_exclusive,
                                     source_scope="US_2026_SOURCE_ONLY"):
    """Source-only research adjudication; no event, account or authority is made.

    Input is caller-hash-guarded ordinary USD common-share cash evidence. Unknown
    availability remains unknown. An unresolved exception is never a quote waiver.
    The default US 2026 contract is unchanged; historical NYSE common USD
    evidence requires an explicit scope and a separately bound listing source.
    """
    result = dict(status="BLOCKED_SOURCE", clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
                  available_at=None, strict_PIT_promotion_eligible=False,
                  production_qualified=False, certified_market_quote_authority=False,
                  source_identity_freeze_required=True)
    try:
        facts, guard = _guard(envelope)
        result["source_projection"] = guard
        if (facts.get("clock_role") != "POST_VERIFIED_ACCOUNTING_ONLY"
                or facts.get("available_at") is not None):
            raise ValueError("POST_VERIFIED_UNKNOWN_CLOCK_ROLE_REQUIRED")
        if source_scope == "US_2026_SOURCE_ONLY":
            if (pd.Timestamp(scope_end_exclusive) > pd.Timestamp("2027-01-01")
                    or pd.Timestamp(facts["record_date"]) < pd.Timestamp("2026-01-01")):
                raise ValueError("POST_VERIFIED_API_2026_SOURCE_SCOPE_ONLY")
            jurisdiction_ok = facts.get("issuer_jurisdiction") == "US"
        elif source_scope == "FROZEN_PRE2026_NYSE_COMMON_USD":
            if (pd.Timestamp(scope_end_exclusive) != pd.Timestamp("2026-01-01")
                    or not pd.Timestamp("2023-01-01") <= pd.Timestamp(facts["record_date"]) < pd.Timestamp("2026-01-01")):
                raise ValueError("FROZEN_HISTORY_2023_2025_SCOPE_REQUIRED")
            jurisdiction_ok = facts.get("issuer_jurisdiction") in ("US", "CA")
            # This opt-in concerns the traded NYSE raw common share, not a
            # transfer of US issuer law to a foreign issuer or a TSX/CAD quote.
            if (facts.get("listed_exchange_jurisdiction") != "US"
                    or facts.get("exchange_rule_applicability") != "NYSE_LISTED_RAW_USD_COMMON_SHARE"
                    or not isinstance(facts.get("exchange_listing_source_reference"), str)
                    or not facts["exchange_listing_source_reference"].strip()):
                raise ValueError("NYSE_FOREIGN_COMMON_SHARE_RULE_APPLICABILITY_UNBOUND")
            _sha(facts.get("exchange_listing_source_fingerprint"), "NYSE_common_share_listing")
        elif source_scope == "FROZEN_PRE2026_LATE_CURRENCY_NYSE_COMMON_USD":
            # A separately pinned same-event late currency fact; the existing
            # US/CA post-verified scope above keeps its original semantics.
            if (pd.Timestamp(scope_end_exclusive) != pd.Timestamp("2026-01-01")
                    or not pd.Timestamp("2023-01-01") <= pd.Timestamp(facts["record_date"]) < pd.Timestamp("2026-01-01")):
                raise ValueError("LATE_CURRENCY_FROZEN_HISTORY_SCOPE_REQUIRED")
            jurisdiction_ok = facts.get("issuer_jurisdiction") == "BM"
            binding = facts.get("late_currency_binding", {})
            exact = dict(security_type="COMMON_STOCK", security_id=facts.get("security_id"),
                ticker=facts.get("ticker"), listing_identity=facts.get("listing_identity"),
                currency="USD", cash_per_raw_share=facts.get("cash_per_raw_share"),
                record_date=facts.get("record_date"), pay_date=facts.get("pay_date"))
            if (facts.get("listed_exchange_jurisdiction") != "US"
                    or facts.get("exchange_rule_applicability") != "NYSE_LISTED_RAW_USD_COMMON_SHARE"
                    or not facts.get("exchange_listing_source_reference")
                    or binding.get("currency_evidence_role") != "SAME_EVENT_LATER_REPORT_USD_ACCOUNTING_FACT"
                    or binding.get("status") != "EXACT_SAME_EVENT_USD_SOURCE_CORROBORATED"
                    or binding.get("available_at") is not None
                    or binding.get("historical_availability_authority") != "UNKNOWN"
                    or binding.get("not_pre_ex_currency_authority") is not True
                    or any(binding.get(k) != v for k,v in exact.items())):
                raise ValueError("LATE_CURRENCY_EXACT_SAME_EVENT_USD_BINDING_REQUIRED")
            original = _day(binding["original_cash_publication_date"], "original_cash_publication")
            later = _day(binding["later_report_publication_date"], "late_report_publication")
            if (str(original.date()) != facts["publication_calendar_date"]
                    or not original < pd.Timestamp(facts["record_date"]) < later):
                raise ValueError("LATE_CURRENCY_PUBLICATION_CLOCKS_MUST_STAY_DISTINCT")
            for name in ("original_cash_source_custody_ref", "later_same_event_currency_custody_ref",
                         "report_cash_paragraph_ref", "same_report_usd_definition_ref"):
                ref = binding[name]
                if (not isinstance(ref,dict) or set(ref)!={"path","sha256"}
                        or not re.match(r"^D:[/\\]",str(ref.get("path")))):
                    raise ValueError("LATE_CURRENCY_PINNED_SOURCE_REF_REQUIRED")
                _sha(ref["sha256"], "late_currency_"+name)
            _sha(facts.get("exchange_listing_source_fingerprint"), "NYSE_common_share_listing")
        elif source_scope=="FROZEN_PRE2026_FOREIGN_NASDAQ_ORDINARY_RAW_SHARE_SAME_FILE_EXPLICIT_USD":
            if (pd.Timestamp(scope_end_exclusive)!=pd.Timestamp("2026-01-01") or not pd.Timestamp("2023-01-01")<=pd.Timestamp(facts["record_date"])<pd.Timestamp("2026-01-01")):
                raise ValueError("FOREIGN_COMMON_FROZEN_HISTORY_SCOPE_REQUIRED")
            jurisdiction_ok=facts.get("issuer_jurisdiction")=="NON_US_FOREIGN_PRIVATE_ISSUER_SOURCE_LITERAL"
            binding=facts.get("foreign_same_file_explicit_usd_binding",{})
            exact=dict(security_id=facts.get("security_id"),ticker=facts.get("ticker"),listing_identity=facts.get("listing_identity"),
                currency="USD",cash_per_raw_share=facts.get("cash_per_raw_share"),record_date=facts.get("record_date"),pay_date=facts.get("pay_date"))
            if (binding.get("cash_evidence_role")!="SAME_FILE_EXPLICIT_USD_ORDINARY_SHARE_GROSS_CASH_FROZEN_RESEARCH_COORDINATE"
                    or binding.get("status")!="PINNED_SAME_FILE_EXPLICIT_USD_DIRECT_ORDINARY_GROSS_CASH_FACT"
                    or binding.get("currency_basis")!="SAME_PROSPECTUS_SUPPLEMENT_EXPLICIT_USD_DEFINITION"
                    or binding.get("share_unit_role")!="SOURCE_DIRECT_NASDAQ_ORDINARY_SHARE_EXACT_FROZEN_RAW_CLASS_ZERO_QUANTITY_BRIDGE"
                    or binding.get("amount_basis")!="DECLARED_GROSS_BEFORE_SOURCE_REPORTED_TAX_NOT_INVESTOR_NET"
                    or binding.get("investor_net_cash_authority")!="UNKNOWN_NOT_ESTIMATED" or binding.get("broker_payment_authority")!="UNKNOWN"
                    or any(binding.get(k) is not False for k in ("share_quantity_effect","source_ADS_claim","source_legal_CUSIP_claim","new_legal_identity_authority","strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                    or binding.get("independent_actual_ex_date") is not None or binding.get("available_at") is not None
                    or any(binding.get(k)!="UNKNOWN" for k in ("historical_availability_authority","exchange_notice_authority","actual_exchange_ex_authority"))
                    or binding.get("ex_coordinate_role")!="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY"
                    or any(binding.get(k)!=v for k,v in exact.items())
                    or facts.get("listed_exchange_jurisdiction")!="US" or facts.get("exchange_rule_applicability")!="NASDAQ_DIRECT_ORDINARY_SHARE_FROZEN_NORMAL_CALENDAR_RESEARCH_ONLY"
                    or facts.get("listing_identity")!="NASDAQ:"+facts["ticker"]
                    or type(binding.get("source_withholding_tax_rate_percent")) not in (int,float) or not 0<=binding["source_withholding_tax_rate_percent"]<=100
                    or not isinstance(binding.get("source_tax_clause"),str) or "after deduction of taxes at the source" not in binding["source_tax_clause"]):
                raise ValueError("FOREIGN_COMMON_EXACT_GROSS_RAW_SHARE_SOURCE_BINDING_REQUIRED")
            filed=_day(binding["actual_SEC_filed_date"],"actual_SEC_filed_date")
            declared=_day(binding["source_declared_date"],"source_declared_date")
            if (str(filed.date())!=facts["publication_calendar_date"] or not declared<pd.Timestamp(facts["record_date"])
                    or binding.get("source_statement_date_role")!="SOURCE_REPORTED_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY"):
                raise ValueError("FOREIGN_COMMON_DISCLOSURE_DECLARATION_AND_UNKNOWN_AVAILABILITY_DISTINCT")
            for name in ("original_HTTP_ref","confirmed_sec_primary_index_metadata_ref"):
                ref=binding[name]
                if not isinstance(ref,dict) or set(ref)!={"path","sha256"} or not re.match(r"^D:[/\\]",str(ref.get("path"))):raise ValueError("FOREIGN_COMMON_PINNED_SOURCE_REF_REQUIRED")
                _sha(ref["sha256"],"foreign_common_"+name)
        elif source_scope == "FROZEN_PRE2026_SEC_CASH_FACT_FROZEN_EX_COORDINATE":
            # Separate retrospective account facts; old publication scopes stay.
            if (pd.Timestamp(scope_end_exclusive) != pd.Timestamp("2026-01-01")
                    or not pd.Timestamp("2023-01-01") <= pd.Timestamp(facts["record_date"]) < pd.Timestamp("2026-01-01")):
                raise ValueError("SEC_CASH_FROZEN_HISTORY_SCOPE_REQUIRED")
            jurisdiction_ok = facts.get("issuer_jurisdiction") == "US"
            binding = facts.get("sec_frozen_cash_binding", {})
            class_a_profile=binding.get("sec_cash_statement_profile")=="SEC_EXPLICIT_CLASS_A_REGULAR_QUARTERLY_COMMON_SHARE_CASH"
            exact = dict(security_id=facts.get("security_id"),ticker=facts.get("ticker"),
                listing_identity=facts.get("listing_identity"),currency="USD",
                cash_per_raw_share=facts.get("cash_per_raw_share"),
                record_date=facts.get("record_date"),pay_date=facts.get("pay_date"))
            if (binding.get("cash_evidence_role") != "SEC_SAME_FILE_CASH_FACT_FROZEN_RESEARCH_EX_COORDINATE"
                    or binding.get("status") != ("PINNED_SEC_INDEX_AND_SAME_FILE_CLASS_A_CASH_FACT" if class_a_profile else "PINNED_SEC_SAME_FILE_CASH_FACT")
                    or binding.get("available_at") is not None
                    or binding.get("historical_availability_authority") != "UNKNOWN"
                    or binding.get("exchange_notice_authority") != "UNKNOWN"
                    or binding.get("actual_exchange_ex_authority") != "UNKNOWN"
                    or binding.get("ex_coordinate_role") != (NSCC_CNS_RECORD_RESEARCH_ROLE if facts.get("cns_bank_holiday_record_binding") is not None else "EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY")
                    or binding.get("currency_basis") != ("INFERRED_USD_US_CHARTER_NYSE_CLASS_A_COMMON_DOLLAR_CONTEXT" if class_a_profile else {"NYSE":"INFERRED_USD_US_SEC_FILER_NYSE_COMMON_DOLLAR_CONTEXT","NASDAQ":"INFERRED_USD_US_SEC_FILER_NASDAQ_COMMON_DOLLAR_CONTEXT"}.get(str(facts.get("listing_identity","")).split(":")[0],"UNSUPPORTED_SEC_COMMON_VENUE"))
                    or type(binding.get("sec_filer_cik")) is not int or binding["sec_filer_cik"] <= 0
                    or binding["sec_filer_cik"] != facts.get("sec_filer_cik")
                    or not isinstance(binding.get("sec_legal_name_literal"),str)
                    or not binding["sec_legal_name_literal"].strip()
                    or any(binding.get(k) != v for k,v in exact.items())):
                raise ValueError("SEC_CASH_EXACT_SAME_FILE_BINDING_REQUIRED")
            if class_a_profile:
                identity=binding.get("frozen_account_identity_binding",{});row=identity.get("original_source_row",{})
                common=identity.get("exact_source_common_class_binding",{})
                if (binding.get("source_transport_profile")!="ISSUER_HOSTED_SEC_8K_HTML_WITH_EXACT_OFFICIAL_INDEX_AND_CLASS_A_COMMON_COVER"
                        or binding.get("source_statement_date_role")!="SOURCE_REPORTED_COMPANY_BOARD_DECLARATION_DAY_NOT_HISTORICAL_AVAILABILITY"
                        or binding.get("source_statement_date")!=binding.get("source_company_declaration_date")
                        or binding.get("private_board_declaration_date") is not None
                        or binding.get("source_original_frozen_class_literal")!="CL A" or binding.get("source_common_class_literal")!="Class A Common Stock"
                        or binding.get("source_CUSIP") is not None or binding.get("source_declared_ex_date") is not None or binding.get("independent_actual_ex_date") is not None
                        or any(binding.get(k) is not False for k in ("source_legal_CUSIP_claim","new_legal_identity_authority","share_quantity_effect","original_frozen_class_rewritten","strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                        or not str(facts.get("listing_identity","")).startswith("NYSE:")
                        or identity.get("source_fingerprint")!=facts.get("identity_source_fingerprint")
                        or identity.get("identity_payload_sha256")!=_hash(identity.get("identity"))
                        or identity.get("identity",{}).get("security_id")!=facts.get("security_id")
                        or row.get("ticker")!=facts.get("ticker") or row.get("title_of_class")!="CL A"
                        or common.get("status")!="PINNED_EXACT_FROZEN_CL_A_SOURCE_CLASS_A_COMMON_RAW_UNIT"
                        or common.get("original_frozen_class_literal")!="CL A" or common.get("source_common_class_literal")!="Class A Common Stock"
                        or common.get("original_frozen_CUSIP")!=row.get("cusip") or not row.get("cusip")
                        or common.get("no_class_alias") is not True
                        or common.get("share_quantity_effect") is not False or common.get("original_frozen_class_rewritten") is not False
                        or {k:common.get("same_file_identity_supplement_ref",{}).get(k) for k in ("path","sha256")}!=binding.get("same_file_cover_ref")
                        or binding.get("same_file_cover_ref")!=binding.get("same_file_registrant_name_custody_ref")
                        or binding.get("source_cash_fragment_ref",{}).get("sha256")!=facts.get("issuer_source_fingerprint")):
                    raise ValueError("SEC_CLASS_A_EXACT_SAME_FILE_AND_ORIGINAL_FROZEN_UNIT_REQUIRED")
                ref=binding.get("historical_SEC_index_metadata_ref")
                if (not isinstance(ref,dict) or set(ref)!={"path","sha256"}
                        or not re.match(r"^D:[/\\]",str(ref.get("path")))):
                    raise ValueError("SEC_CLASS_A_EXACT_HISTORICAL_INDEX_REF_REQUIRED")
                _sha(ref["sha256"],"SEC_Class_A_historical_index")
            filed = _day(binding["actual_SEC_filed_date"], "actual_SEC_filed_date")
            # These retrospective source dates are neither private Board clocks
            # nor historical public-availability or actual exchange-ex authority.
            frozen_common_roles={
                "HTML_AUDIT_COMMITTEE_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT":"ORIGINAL_AUDIT_COMMITTEE_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY",
                "HTML_DECLARATION_RECORD_PAYMENT_COMMON_CASH_TABLE_ROW":"ORIGINAL_TABLE_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY",
                "STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION":"STATIC_SUBMISSION_PUBLIC_ACCEPTANCE_DAY_NOT_BOARD_DATE"}
            profile=binding.get("sec_cash_statement_profile")
            if profile in frozen_common_roles:
                if (binding.get("source_transport_profile") not in (("SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_EX99_ATTACHMENT","SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_PRIMARY_BODY_CASH") if profile=="STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION" else ("SEC_PRIMARY_HTML_WITH_EXACT_HISTORICAL_FILING_METADATA",))
                        or binding.get("source_statement_date_role")!=frozen_common_roles[profile]
                        or binding.get("private_board_declaration_date") is not None
                        or binding.get("source_frozen_common_identity_role")!="EXACT_FROZEN_COM_RAW_COMMON_CASH_NAMESPACE_NO_ISSUER_NAME_ALIAS"
                        or binding.get("source_CUSIP") is not None or binding.get("source_common_CUSIP_identity_custody_ref") is not None
                        or binding.get("source_legal_CUSIP_claim") is not False or binding.get("new_legal_identity_authority") is not False
                        or any(binding.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
                    raise ValueError("SEC_CASH_EXACT_FROZEN_COMMON_STATEMENT_ROLE_REQUIRED")
            if binding["private_board_declaration_date"] is None:
                old_announcement=(binding.get("sec_cash_statement_profile") in ("COMPANY_DECLARED_EXPLICIT_COMMON_CASH_STATEMENT", "DATED_ISSUER_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT")
                    and binding.get("source_statement_date_role")=="PUBLIC_ANNOUNCEMENT_DAY_NOT_PRIVATE_BOARD_DATE")
                primary_HTML=(binding.get("source_transport_profile")=="SEC_PRIMARY_HTML_WITH_EXACT_HISTORICAL_FILING_METADATA"
                    and (binding.get("sec_cash_statement_profile"),binding.get("source_statement_date_role")) in (
                        ("HTML_EXPLICIT_COMMON_CASH_STATEMENT","PUBLIC_ANNOUNCEMENT_DAY_NOT_PRIVATE_BOARD_DATE"),
                        ("HTML_DECLARATION_RECORD_DISTRIBUTION_TABLE_ROW","ORIGINAL_TABLE_DECLARATION_DATE_NOT_PRIVATE_BOARD_DAY"),
                        ("HTML_AUDIT_COMMITTEE_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT","ORIGINAL_AUDIT_COMMITTEE_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY"),
                        ("HTML_DECLARATION_RECORD_PAYMENT_COMMON_CASH_TABLE_ROW","ORIGINAL_TABLE_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY")))
                static_submission=(profile=="STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION"
                    and binding.get("source_transport_profile") in ("SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_EX99_ATTACHMENT","SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_PRIMARY_BODY_CASH")
                    and binding.get("source_statement_date_role")=="STATIC_SUBMISSION_PUBLIC_ACCEPTANCE_DAY_NOT_BOARD_DATE"
                    and binding.get("static_submission_transport_proof",{}).get("schema")==("STATIC_SEC_SAME_ACCESSION_PRIMARY_BODY_CASH_TRANSPORT_V1" if binding["source_transport_profile"]=="SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_PRIMARY_BODY_CASH" else "STATIC_SEC_SAME_ACCESSION_PARENT_AND_EX99_TRANSPORT_V1")
                    and binding["static_submission_transport_proof"].get("unit_basis")=="ORIGINAL_PRE_EX_CURRENT_COMMON_SHARE_DECLARATION"
                    and binding["static_submission_transport_proof"].get("source_publication_not_press_dateline") is True
                    and binding["static_submission_transport_proof"].get("share_quantity_effect") is False
                    and binding.get("issuer_relation_role")=="EXACT_DATED_FROZEN_COM_AND_STATIC_UNIQUE_COMMON_SYMBOL"
                    and binding.get("issuer_name_alias_used") is False
                    and binding.get("source_statement_date")==str(pd.Timestamp(binding["static_submission_transport_proof"]["accepted_at_utc"]).tz_convert("America/New_York").date())
                    and binding.get("static_submission_dated_raw_identity_proof",{}).get("same_dated_UID_and_SID") is True
                    and binding["static_submission_dated_raw_identity_proof"].get("accounting_sid")==facts.get("security_id")
                    and binding["static_submission_dated_raw_identity_proof"].get("new_legal_CUSIP_authority") is False
                    and binding["static_submission_dated_raw_identity_proof"].get("share_quantity_effect") is False)
                if static_submission and binding["source_transport_profile"]=="SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_PRIMARY_BODY_CASH":
                    proof=binding["static_submission_transport_proof"]
                    static_submission=(proof.get("cash_document_role")=="ORIGINAL_PRIMARY_SEC_BODY_CURRENT_COMMON_CASH_DECLARATION"
                        and proof.get("parent_document")==proof.get("cash_attachment_document")
                        and proof.get("parent_document",{}).get("type") in ("8-K","10-Q","10-K")
                        and proof.get("cash_document_published_at_utc")==proof.get("accepted_at_utc"))
                if static_submission:
                    listed=binding.get("source_unique_listed_common_class");declared=binding.get("source_cash_explicit_common_class")
                    if listed is not None or declared is not None:
                        static_submission=(listed in ("A","B","C") and listed==declared
                            and binding.get("source_class_match_role")=="EXPLICIT_SINGLE_LISTED_CLASS_AND_SAME_CASH_CLASS_WITH_EXACT_DATED_RAW_SID"
                            and binding.get("original_frozen_class_literal")=="COM"
                            and binding.get("original_frozen_class_rewritten") is False)
                if not (old_announcement or primary_HTML or class_a_profile or static_submission):
                    raise ValueError("SEC_CASH_UNKNOWN_PRIVATE_DAY_REQUIRES_EXACT_ANNOUNCEMENT_ROLE")
                private=_day(binding["source_statement_date"],"source_original_statement_date" if profile in frozen_common_roles else "source_public_announcement_date")
            else:
                private = _day(binding["private_board_declaration_date"], "private_board_date")
            # Current retrieval custody is an operational clock, not 2026
            # market/test content or a historical publication authority.
            capture = pd.Timestamp(binding["current_capture_utc"])
            if pd.isna(capture) or capture.tzinfo is None:
                raise ValueError("SEC_CASH_AWARE_CURRENT_CUSTODY_REQUIRED")
            if (str(filed.date()) != facts["publication_calendar_date"] or private > filed
                    or capture < filed.tz_localize("UTC")):
                raise ValueError("SEC_CASH_TRUE_FILED_AND_CURRENT_CAPTURE_CLOCKS_REQUIRED")
            for name in ("sec_cash_source_custody_ref","same_file_cover_ref",
                         "same_file_registrant_name_custody_ref","original_HTTP_ref","source_cash_fragment_ref"):
                ref = binding[name]
                if (not isinstance(ref,dict) or set(ref)!={"path","sha256"}
                        or not re.match(r"^D:[/\\]",str(ref.get("path")))):
                    raise ValueError("SEC_CASH_PINNED_SOURCE_REF_REQUIRED")
                _sha(ref["sha256"], "SEC_cash_"+name)
        elif source_scope=="FROZEN_PRE2026_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP":
            if facts.get('cash_component_group_binding',{}).get('cash_evidence_role')=='SOURCE_BOUND_EXPLICIT_TOTAL_BASE_AND_VARIABLE_COMMON_CASH_COMPONENT_GROUP':
                binding=facts['cash_component_group_binding']
                _validate_explicit_total_base_variable_group(facts,binding,scope_end_exclusive=scope_end_exclusive)
                jurisdiction_ok=True
            else:
                from decimal import Decimal
                if (pd.Timestamp(scope_end_exclusive)!=pd.Timestamp("2026-01-01")
                        or not pd.Timestamp("2023-01-01")<=pd.Timestamp(facts["record_date"])<pd.Timestamp("2026-01-01")):
                    raise ValueError("COMPONENT_GROUP_FROZEN_HISTORY_SCOPE_REQUIRED")
                jurisdiction_ok=facts.get("issuer_jurisdiction")=="US"
                binding=facts.get("cash_component_group_binding",{})
                identity=binding.get("frozen_account_identity_binding",{});row=identity.get("original_source_row",{})
                expected=dict(security_id=facts.get("security_id"),ticker=facts.get("ticker"),listing_identity=facts.get("listing_identity"),
                    currency="USD",cash_per_raw_share=facts.get("cash_per_raw_share"),record_date=facts.get("record_date"),
                    pay_date=facts.get("pay_date"),ex_date=facts["exact_frozen_event_key"]["effective_date"],
                    publication_calendar_date=facts.get("publication_calendar_date"))
                if (binding.get("status")!="PINNED_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP"
                        or binding.get("cash_evidence_role")!="SOURCE_BOUND_ANNUAL_AND_QUARTERLY_COMMON_CASH_COMPONENT_GROUP"
                        or binding.get("amount_aggregation_role")!="EXACT_ORIGINAL_DECIMAL_STRINGS_SUM_ONCE_PER_RAW_COMMON_SHARE"
                        or binding.get("clock_applicability_role")!="EXPLICIT_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION"
                        or binding.get("consumption_set_role")!="ORDINARY_PAY_END_CLOCK_SET_PLUS_EXPLICIT_SAME_CLOCK_COMPONENT_GROUPS"
                        or binding.get("accounting_clock_convention")!="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION"
                        or binding.get("annual_ordinary_or_quarterly_reclassification") is not False
                        or binding.get("available_at") is not None or binding.get("historical_availability_authority")!="UNKNOWN"
                        or binding.get("exchange_notice_authority")!="UNKNOWN" or binding.get("actual_exchange_ex_authority")!="UNKNOWN"
                        or binding.get("original_full_HTTP_ref") is not None
                        or binding.get("partial_custody_role")!="EXACT_CAPTURED_BYTE_FRAGMENT_WITH_OPAQUE_WHOLE_BODY_COMMITMENT_NOT_RETAINED_FULL_BODY"
                        or binding.get("currency_basis")!="INFERRED_USD_SAME_SOURCE_US_COMMON_SHARE_COMPONENTS"
                        or binding.get("issuer_relation_role")!="EXACT_RESOLVED_FROZEN_SYMBOL_COMMON_CLASS_RAW_SHARE_COORDINATE_NOT_NAME_EQUIVALENCE"
                        or binding.get("issuer_name_alias_used") is not False or not binding.get("source_legal_issuer_literal")
                        or binding.get("original_frozen_issuer_literal")!=row.get("issuer_name")
                        or any(binding.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                        or any(binding.get(k)!=value for k,value in expected.items())
                        or identity.get("available_at") is not None or identity.get("legal_identity_authority_granted") is not False
                        or identity.get("historical_availability_qualified") is not False
                        or identity.get("identity_clock_role")!="ORIGINAL_FROZEN_EFFECTIVE_INTERVAL_NOT_PUBLICATION"
                        or identity.get("identity",{}).get("security_id")!=facts.get("security_id")
                        or row.get("title_of_class")!="COM" or row.get("security_id_type")!="CUSIP"
                        or row.get("security_id")!=row.get("cusip") or row.get("ticker")!=facts["ticker"]
                        or binding.get("original_exact_key")!=facts["exact_frozen_event_key"]):
                    raise ValueError("COMPONENT_GROUP_EXPLICIT_CLASS_UNIT_CLOCK_AND_IDENTITY_REQUIRED")
                parts=binding.get("cash_components")
                kinds=("ANNUAL_COMMON_SHARE_CASH_DIVIDEND","QUARTERLY_COMMON_SHARE_CASH_DIVIDEND")
                component_fields=("component_kind","source_amount_literal","source_component_literal","component_original_bytes_sha256",
                    "local_fragment_byte_range","original_HTTP_byte_range","source_custody_ref","original_cash_fragment_ref","cash_text_projection_ref")
                if not isinstance(parts,list) or len(parts)!=2 or [part.get("component_kind") for part in parts]!=list(kinds):
                    raise ValueError("COMPONENT_GROUP_TWO_DISTINCT_ORIGINAL_CLASSES_REQUIRED")
                for part in parts:
                    if (not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",str(part.get("source_amount_literal")))
                            or part.get("component_id")!=_hash({k:part[k] for k in component_fields})
                            or part.get("date_binding_role")!="SAME_SOURCE_BOTH_COMPONENTS_COMMON_DATE_CLAUSE"
                            or any(part.get(k)!=expected[k] for k in ("security_id","ticker","currency","record_date","pay_date","ex_date"))
                            or part.get("amount_unit")!=USD_PER_RAW_OLD_SHARE or part.get("quantity_coordinate")!=RAW_OLD_SHARE_COORDINATE):
                        raise ValueError("COMPONENT_GROUP_SOURCE_COMPONENT_HASH_UNIT_OR_CLOCK_CHANGED")
                    _sha(part.get("component_original_bytes_sha256"),"original_cash_component")
                total=sum((Decimal(part["source_amount_literal"]) for part in parts),Decimal("0"))
                if (total<=0 or float(total)!=facts["cash_per_raw_share"] or format(total,"f")!=binding.get("total_cash_amount_literal")
                        or binding.get("group_id")!=_hash(dict(components=parts,original_key=facts["exact_frozen_event_key"]))):
                    raise ValueError("COMPONENT_GROUP_EXACT_SOURCE_DECIMAL_SUM_AND_HASH_REQUIRED")
                for name in ("component_group_source_ref","original_source_custody_ref","original_cash_fragment_ref","original_cash_text_ref"):
                    ref=binding[name]
                    if (not isinstance(ref,dict) or set(ref) not in ({"path","sha256"},{"path","sha256","bytes"})
                            or not re.match(r"^D:[/\\]",str(ref.get("path")))
                            or ("bytes" in ref and (type(ref["bytes"]) is not int or ref["bytes"]<=0))):
                        raise ValueError("COMPONENT_GROUP_ORIGINAL_PINNED_SOURCE_REF_REQUIRED")
                    _sha(ref["sha256"],"cash_component_group_"+name)
                _sha(binding.get("opaque_HTTP_sha256"),"original_opaque_HTTP")
                capture=pd.Timestamp(binding["current_capture_utc"])
                if pd.isna(capture) or capture.tzinfo is None:
                    raise ValueError("COMPONENT_GROUP_AWARE_CURRENT_CAPTURE_REQUIRED")
        elif source_scope=="FROZEN_PRE2026_DATED_NOTICE_COMMON_UNIT_BRIDGE":
            if (pd.Timestamp(scope_end_exclusive)!=pd.Timestamp("2026-01-01")
                    or not pd.Timestamp("2023-01-01")<=pd.Timestamp(facts["record_date"])<pd.Timestamp("2026-01-01")):
                raise ValueError("DATED_COMMON_UNIT_FROZEN_HISTORY_SCOPE_REQUIRED")
            jurisdiction_ok=facts.get("issuer_jurisdiction")=="US"
            binding=facts.get("dated_common_unit_bridge_binding",{})
            exact=dict(security_id=facts.get("security_id"),ticker=facts.get("ticker"),listing_identity=facts.get("listing_identity"),
                currency="USD",cash_per_raw_share=facts.get("cash_per_raw_share"),record_date=facts.get("record_date"),pay_date=facts.get("pay_date"))
            identity=binding.get("frozen_account_identity_binding",{});row=identity.get("original_source_row",{})
            if (binding.get("status")!="PINNED_DATED_NOTICE_COMMON_UNIT_BRIDGE"
                    or binding.get("cash_evidence_role")!="DATED_NOTICE_SAME_ISSUER_FROZEN_COMMON_UNIT_RESEARCH_BRIDGE"
                    or binding.get("unit_source_role")!="ORIGINAL_FROZEN_COM_RAW_SHARE_AND_REPORT_COMMON_POLICY_AND_DATED_NOTICE"
                    or binding.get("available_at") is not None or binding.get("historical_availability_authority")!="UNKNOWN"
                    or binding.get("exchange_notice_authority")!="UNKNOWN" or binding.get("actual_exchange_ex_authority")!="UNKNOWN"
                    or binding.get("ex_coordinate_role")!="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY"
                    or binding.get("currency_basis")!="INFERRED_USD_SAME_US_COMMON_POLICY_AND_DATED_DOLLAR_NOTICE"
                    or binding.get("notice_publication_date")!=facts.get("publication_calendar_date")
                    or binding.get("private_board_declaration_date") is not None or binding.get("report_publication_date") is not None
                    or binding.get("amount_match_is_not_class_evidence") is not True
                    or binding.get("report_currency_or_amount_not_copied_into_notice") is not True
                    or any(binding.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                    or any(binding.get(k)!=v for k,v in exact.items())
                    or identity.get("available_at") is not None or identity.get("legal_identity_authority_granted") is not False
                    or identity.get("historical_availability_qualified") is not False
                    or identity.get("identity_clock_role")!="ORIGINAL_FROZEN_EFFECTIVE_INTERVAL_NOT_PUBLICATION"
                    or identity.get("identity",{}).get("security_id")!=facts.get("security_id")
                    or row.get("title_of_class")!="COM" or row.get("security_id_type")!="CUSIP"
                    or row.get("security_id")!=row.get("cusip") or row.get("ticker")!=facts["ticker"]):
                raise ValueError("DATED_COMMON_UNIT_THREE_SOURCE_ROLES_REQUIRED")
            for name in ("original_notice_custody_ref","original_notice_body_ref","original_notice_transport_ref",
                         "original_cash_fragment_ref","original_header_projection_ref","report_common_policy_custody_ref",
                         "original_report_ref","original_report_cash_page_ref","original_report_cover_page_ref"):
                ref=binding[name]
                if not isinstance(ref,dict) or set(ref)!={"path","sha256"} or not re.match(r"^D:[/\\]",str(ref.get("path"))):
                    raise ValueError("DATED_COMMON_UNIT_PINNED_SOURCE_REF_REQUIRED")
                _sha(ref["sha256"],"dated_common_unit_"+name)
            descriptor=(binding.get("notice_descriptor_profile"),binding.get("notice_capture_clock_role"))
            if descriptor not in (
                    ("GENERIC_ORIGINAL_HTTP_CASH_CUSTODY_DESCRIPTOR_V1","ACTUAL_TRANSPORT_CURRENT_CAPTURE_UTC_NOT_PUBLICATION"),
                    ("ISSUER_DATED_HTML_CASH_PREFIX_CUSTODY_DESCRIPTOR_V1","ACTUAL_TRANSPORT_HTTP_REQUEST_END_UTC_NOT_PUBLICATION")):
                raise ValueError("DATED_COMMON_UNIT_ORIGINAL_CAPTURE_ROLE_REQUIRED")
            if descriptor[0]=="ISSUER_DATED_HTML_CASH_PREFIX_CUSTODY_DESCRIPTOR_V1":
                projection_capture=pd.Timestamp(binding["notice_projection_capture_utc"])
                if pd.isna(projection_capture) or projection_capture.tzinfo is None or projection_capture<pd.Timestamp(binding["notice_current_capture_utc"]):
                    raise ValueError("DATED_COMMON_UNIT_SEPARATE_PROJECTION_CAPTURE_REQUIRED")
                for name in ("original_notice_identity_prefix_ref","original_notice_identity_prefix_text_ref"):
                    ref=binding[name]
                    if not isinstance(ref,dict) or set(ref)!={"path","sha256"} or not re.match(r"^D:[/\\]",str(ref.get("path"))):
                        raise ValueError("DATED_COMMON_UNIT_PINNED_PREFIX_SOURCE_REF_REQUIRED")
                    _sha(ref["sha256"],"dated_common_unit_"+name)
            elif binding.get("notice_projection_capture_utc") is not None:
                raise ValueError("DATED_COMMON_UNIT_UNDECLARED_PROJECTION_CAPTURE")
            for name in ("notice_current_capture_utc","report_current_capture_utc"):
                capture=pd.Timestamp(binding[name])
                if pd.isna(capture) or capture.tzinfo is None:
                    raise ValueError("DATED_COMMON_UNIT_AWARE_CAPTURE_REQUIRED")
        elif source_scope == "FROZEN_PRE2026_REPORT_CASH_TABLE_FROZEN_EX_COORDINATE":
            if (pd.Timestamp(scope_end_exclusive)!=pd.Timestamp("2026-01-01")
                    or not pd.Timestamp("2023-01-01")<=pd.Timestamp(facts["record_date"])<pd.Timestamp("2026-01-01")):
                raise ValueError("REPORT_CASH_FROZEN_HISTORY_SCOPE_REQUIRED")
            jurisdiction_ok=facts.get("issuer_jurisdiction")=="US"
            binding=facts.get("report_frozen_cash_binding",{})
            exact=dict(security_id=facts.get("security_id"),ticker=facts.get("ticker"),
                listing_identity=facts.get("listing_identity"),currency="USD",
                cash_per_raw_share=facts.get("cash_per_raw_share"),record_date=facts.get("record_date"),pay_date=facts.get("pay_date"))
            if (binding.get("cash_evidence_role")!="REPORT_SAME_FILE_COMMON_CASH_TABLE_FROZEN_RESEARCH_EX_COORDINATE"
                    or binding.get("status")!="PINNED_REPORT_SAME_FILE_COMMON_CASH_FACT"
                    or binding.get("available_at") is not None or binding.get("publication_calendar_date") is not None
                    or binding.get("private_board_declaration_date") is not None
                    or binding.get("historical_availability_authority")!="UNKNOWN"
                    or binding.get("exchange_notice_authority")!="UNKNOWN"
                    or binding.get("actual_exchange_ex_authority")!="UNKNOWN"
                    or binding.get("ex_coordinate_role")!="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY"
                    or binding.get("currency_basis")!="INFERRED_USD_US_REPORT_NYSE_COMMON_DOLLAR_CONTEXT"
                    or (binding.get("source_descriptor_profile"),binding.get("transport_role")) not in (
                        (None,"THIRD_PARTY_MIRROR_OF_ORIGINAL_ISSUER_REPORT_SAME_FILE_COMMON_CASH"),
                        ("ACTUAL_MIRROR_CAPTURED_REPORT_DESCRIPTOR_V1","THIRD_PARTY_PUBLIC_MIRROR_OF_ORIGINAL_ISSUER_REPORT"))
                    or facts.get("publication_calendar_date") is not None
                    or any(binding.get(k)!=v for k,v in exact.items())):
                raise ValueError("REPORT_CASH_EXACT_SAME_FILE_BINDING_REQUIRED")
            if binding.get("source_descriptor_profile")=="ACTUAL_MIRROR_CAPTURED_REPORT_DESCRIPTOR_V1":
                if (binding.get("current_capture_clock_role")!="ACTUAL_CURRENT_CAPTURE_UTC_NOT_HTTP_END_OR_PUBLICATION"
                        or binding.get("source_transport_flags_role")!="ORIGINAL_TRANSPORT_UNDECLARED_NOT_INVENTED_SOURCE_FLAGS"
                        or any(binding.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                        or binding.get("actual_captured_body_sha256")!=binding.get("original_report_ref",{}).get("sha256")
                        or type(binding.get("actual_captured_byte_count")) is not int
                        or binding["actual_captured_byte_count"]<=0):
                    raise ValueError("REPORT_CASH_ACTUAL_CAPTURE_DESCRIPTOR_REQUIRED")
                _sha(binding["actual_captured_body_sha256"],"report_original_body")
            capture=pd.Timestamp(binding["current_capture_utc"])
            if pd.isna(capture) or capture.tzinfo is None:
                raise ValueError("REPORT_CASH_AWARE_CURRENT_CUSTODY_REQUIRED")
            interval=binding.get("declaration_month_interval")
            if interval is not None:
                start=_day(interval["start_inclusive"],"declaration_month_start")
                end=_day(interval["end_exclusive"],"declaration_month_end")
                if (start.day!=1 or end!=start+pd.offsets.MonthBegin(1)
                        or str(pd.Timestamp(interval["source_literal"]).date())!=str(start.date())
                        or interval.get("precision")!="MONTH_ONLY_NOT_A_DAY_OR_PUBLICATION"
                        or end>pd.Timestamp(facts["exact_frozen_event_key"]["effective_date"])):
                    raise ValueError("REPORT_CASH_DECLARATION_MONTH_MUST_BE_WHOLE_PRE_EX")
            for name in ("report_cash_source_custody_ref","original_report_ref","source_transport_ref",
                         "source_cash_page_ref","same_file_cover_fragment_ref"):
                ref=binding[name]
                if (not isinstance(ref,dict) or set(ref)!={"path","sha256"}
                        or not re.match(r"^D:[/\\]",str(ref.get("path")))):
                    raise ValueError("REPORT_CASH_PINNED_SOURCE_REF_REQUIRED")
                _sha(ref["sha256"],"report_cash_"+name)
        else:
            raise ValueError("POST_VERIFIED_SOURCE_SCOPE_UNKNOWN")
        if (not jurisdiction_ok
                or facts.get("security_type") != "COMMON_STOCK"
                or facts.get("listing_identity") not in (("NYSE:"+facts["ticker"],"NASDAQ:"+facts["ticker"]) if source_scope in ("FROZEN_PRE2026_SEC_CASH_FACT_FROZEN_EX_COORDINATE","FROZEN_PRE2026_FOREIGN_NASDAQ_ORDINARY_RAW_SHARE_SAME_FILE_EXPLICIT_USD") else ("NYSE:"+facts["ticker"],))
                or facts.get("identity_unique") is not True
                or not isinstance(facts.get("security_id"), str) or not facts["security_id"]
                or facts["security_id"].upper().startswith("FROZEN_VENDOR:")
                or any(token in facts["security_id"].upper() for token in
                       ("UNKNOWN", "NOT_EXTRACTED", "UNCONFIRMED", "NOT_REQUIRED", "PLACEHOLDER"))
                or facts.get("currency") != "USD"
                or facts.get("amount_unit") != USD_PER_RAW_OLD_SHARE
                or facts.get("quantity_coordinate") != RAW_OLD_SHARE_COORDINATE):
            raise ValueError("NORMAL_CASH_IDENTITY_CURRENCY_OR_RAW_UNIT_UNBOUND")
        _sha(facts.get("issuer_source_fingerprint"), "issuer_cash_terms")
        _sha(facts.get("identity_source_fingerprint"), "dated_security_identity")
        component_group_scope=source_scope=="FROZEN_PRE2026_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP"
        class_qualified=(facts.get("ordinary_cash_confirmed") is False and facts.get("common_cash_component_group_confirmed") is True
                        if component_group_scope else facts.get("ordinary_cash_confirmed") is True)
        if (not class_qualified
                or facts.get("noncash_flags_absent") is not True
                or facts.get("special_or_due_bill_indicator") is not False
                or facts.get("late_notice_indicator") is not False):
            raise ValueError("NORMAL_CASH_EXCEPTION_OR_CLASSIFICATION_UNBOUND")
        if (calendar_binding.get("status") != "SOURCE_BOUND_LEGAL_SESSION_CALENDAR"
                or calendar_binding.get("session_dates_sha256") !=
                    _hash([str(pd.Timestamp(day).date()) for day in calendar])):
            raise ValueError("UNBOUND_LEGAL_SESSION_CALENDAR")
        _sha(calendar_binding.get("source_fingerprint"), "calendar")
        if not calendar_binding.get("source_reference"):
            raise ValueError("CALENDAR_SOURCE_REFERENCE_REQUIRED")
        cns_record=facts.get("cns_bank_holiday_record_binding")
        if cns_record is not None:
            if (source_scope=="US_2026_SOURCE_ONLY"
                    or cns_record.get("calendar_binding")!=calendar_binding
                    or facts.get("closed_record_research_binding") is not None
                    or facts.get("nyse_nonbusiness_record_binding") is not None
                    or facts.get("nyse_post_t1_nonbusiness_record_binding") is not None):
                raise ValueError("NSCC_CNS_SCOPE_OR_CALENDAR_OR_POLICY_CONFLICT")
            validate_cns_bank_holiday_record_binding(cns_record,calendar=calendar,
                record_date=facts["record_date"],scope_end_exclusive=scope_end_exclusive,facts=facts)
        closed_record=facts.get("closed_record_research_binding")
        if closed_record is not None:
            cb=closed_record.get("calendar_binding",{})
            if (pd.Timestamp(scope_end_exclusive)!=pd.Timestamp("2026-01-01")
                    or source_scope=="US_2026_SOURCE_ONLY"
                    or {k:cb.get(k) for k in calendar_binding}!=calendar_binding):
                raise ValueError("CLOSED_RECORD_RESEARCH_SCOPE_AND_CALENDAR_REQUIRED")
            validate_closed_record_research_binding(closed_record,calendar=calendar,
                record_date=facts["record_date"],pay_date=facts["pay_date"],
                ex_date=facts["exact_frozen_event_key"]["effective_date"],security_id=facts["security_id"],
                ticker=facts["ticker"],original_key=facts["exact_frozen_event_key"])
        nyse_nonbusiness=facts.get("nyse_nonbusiness_record_binding")
        if nyse_nonbusiness is not None:
            if (source_scope!="FROZEN_PRE2026_REPORT_CASH_TABLE_FROZEN_EX_COORDINATE"
                    or nyse_nonbusiness.get("calendar_binding")!=calendar_binding):
                raise ValueError("NYSE_NONBUSINESS_REPORT_SCOPE_AND_CALENDAR_REQUIRED")
        ex, rule_key = normal_cash_ex_date(facts["record_date"], calendar,
            scope_end_exclusive=scope_end_exclusive,
            **(dict(policy=NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH,cns_bank_holiday_record_binding=cns_record)
                if cns_record is not None else dict(policy=CLOSED_RECORD_RESEARCH_POLICY,closed_record_research_binding=closed_record)
                if closed_record is not None else dict(policy=NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH,
                nyse_nonbusiness_record_binding=nyse_nonbusiness) if nyse_nonbusiness is not None
                else dict(policy="NYSE_T1_TRANSITION_2024")))
        if nyse_nonbusiness is not None:
            result["nyse_nonbusiness_record_binding"]=copy.deepcopy(nyse_nonbusiness)
        if closed_record is not None:
            rule=dict(kind="EXPLICIT_FROZEN_ACCOUNTING_RESEARCH_COORDINATE_NOT_EXCHANGE_RULE",
                source_reference=closed_record["official_closure_source_ref"]["path"],
                source_fingerprint=closed_record["official_closure_source_ref"]["sha256"])
            result["closed_record_research_binding"]=copy.deepcopy(closed_record)
        else:
            rule = rule_sources[rule_key]
            _sha(rule.get("source_fingerprint"), "normal_cash_ex_rule")
            if not isinstance(rule.get("source_reference"), str) or not rule["source_reference"].strip():
                raise ValueError("EX_RULE_SOURCE_REFERENCE_REQUIRED")
            expected = {"TPLUS2": ("2017-09-05", "2024-05-28"),
                        "NYSE_T1_TRANSITION": ("2024-05-28", "2024-05-29"),
                        "TPLUS1": ("2024-05-28", None)}
            start, until = expected[rule_key]
            kinds = {"TPLUS2": "FINRA_17_19_NORMAL_SMALL_CASH",
                     "NYSE_T1_TRANSITION": "NYSE_2024_ANNUAL_GUIDANCE_NORMAL_CASH_TRANSITION",
                     "TPLUS1": "FINRA_24_04_NORMAL_SMALL_CASH"}
            if (rule.get("kind") != kinds[rule_key]
                    or rule.get("effective_from") != start
                    or rule.get("effective_until_exclusive") != until):
                raise ValueError("EX_RULE_INTERVAL_OR_KIND_CHANGED")
        if facts.get("pay_date_status") != "SOURCE_FIXED_ANNOUNCED_SCHEDULE":
            raise ValueError("FIXED_ANNOUNCED_PAYMENT_SCHEDULE_REQUIRED")
        publication = pd.Timestamp(facts["publication_calendar_date"])
        pay = pd.Timestamp(facts["pay_date"])
        sec_fact_scope = source_scope == "FROZEN_PRE2026_SEC_CASH_FACT_FROZEN_EX_COORDINATE"
        report_fact_scope = source_scope == "FROZEN_PRE2026_REPORT_CASH_TABLE_FROZEN_EX_COORDINATE"
        dated_unit_scope=source_scope=="FROZEN_PRE2026_DATED_NOTICE_COMMON_UNIT_BRIDGE"
        foreign_common_scope=source_scope=="FROZEN_PRE2026_FOREIGN_NASDAQ_ORDINARY_RAW_SHARE_SAME_FILE_EXPLICIT_USD"
        frozen_fact_scope = sec_fact_scope or report_fact_scope or dated_unit_scope or component_group_scope or foreign_common_scope
        if report_fact_scope:
            if (facts.get("publication_calendar_date") is not None
                    or pd.isna(pay) or pay.tzinfo is not None or pay!=pay.normalize()
                    or pay<pd.Timestamp(facts["record_date"])):
                raise ValueError("REPORT_CASH_UNKNOWN_PUBLICATION_OR_FIXED_PAY_UNBOUND")
        elif sec_fact_scope or foreign_common_scope or (component_group_scope and binding.get("cash_evidence_role")=="SOURCE_BOUND_EXPLICIT_TOTAL_BASE_AND_VARIABLE_COMMON_CASH_COMPONENT_GROUP"):
            if (pd.isna(publication) or publication.tzinfo is not None
                    or publication != publication.normalize()
                    or str(publication.date()) != binding["actual_SEC_filed_date"]
                    or pd.isna(pay) or pay.tzinfo is not None or pay != pay.normalize()
                    or pay < pd.Timestamp(facts["record_date"])):
                raise ValueError("SEC_CASH_ACTUAL_FILED_OR_FIXED_PAY_UNBOUND")
        else:
            if (pd.isna(publication) or publication.tzinfo is not None
                    or publication != publication.normalize() or publication >= ex
                    or (pd.Timestamp(facts["record_date"]) - publication).days < 10
                    or pd.isna(pay) or pay.tzinfo is not None or pay != pay.normalize()
                    or pay < pd.Timestamp(facts["record_date"])):
                raise ValueError("ADVANCE_PUBLICATION_OR_FIXED_PAY_UNBOUND")
        derived_role = "DERIVED_NYSE_NORMAL_EX_FROM_RECORD_DATE_MATCHED_EXACT_FROZEN_EVENT"
        expected_ex_role=(NSCC_CNS_RECORD_RESEARCH_ROLE if cns_record is not None else CLOSED_RECORD_RESEARCH_ROLE
            if closed_record is not None else "EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY")
        if frozen_fact_scope and facts.get("ex_date_provenance_role") != expected_ex_role:
            raise ValueError("SEC_CASH_EXACT_FROZEN_RESEARCH_COORDINATE_REQUIRED")
        if (cns_record is not None or frozen_fact_scope or (source_scope in ("FROZEN_PRE2026_NYSE_COMMON_USD", "FROZEN_PRE2026_LATE_CURRENCY_NYSE_COMMON_USD")
                and facts.get("ex_date_provenance_role") == derived_role)):
            frozen = facts["exact_frozen_event_key"]
            if (type(facts.get("frozen_event_exact_row_count")) is not int
                    or facts["frozen_event_exact_row_count"] != 1
                    or set(frozen) != {"ticker", "effective_date", "reason", "source_reference", "source_fingerprint"}
                    or frozen["ticker"] != facts["ticker"]
                    or frozen["effective_date"] != str(ex.date())
                    or frozen["reason"] != "VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY"
                    or not isinstance(frozen["source_reference"], str) or not frozen["source_reference"].strip()
                    or facts.get("frozen_event_key_sha256") != _hash(frozen)):
                raise ValueError("EXACT_FROZEN_EVENT_DISAGREES_WITH_DERIVED_NORMAL_EX")
            _sha(frozen["source_fingerprint"], "original_frozen_event")
            _sha(facts.get("frozen_catalogue_source_fingerprint"), "original_frozen_catalogue")
        else:
            if (type(facts.get("vendor_exact_row_count")) is not int
                    or facts["vendor_exact_row_count"] != 1
                    or facts.get("vendor_ex_field") != "ex_div_date"
                    or facts.get("vendor_named_ex_date") != str(ex.date())):
                raise ValueError("NAMED_VENDOR_EX_DISAGREES_WITH_NORMAL_RULE")
            _sha(facts.get("vendor_source_fingerprint"), "vendor_named_ex")
        sessions = tuple(pd.Timestamp(day) for day in calendar)
        pos = sessions.index(ex)
        if pos == 0:
            raise ValueError("PRE_EX_CLOSE_SESSION_MISSING")
        price = facts["prior_raw_close"]
        if (price.get("ticker") != facts["ticker"]
                or price.get("security_id") != facts["security_id"]
                or price.get("trade_date") != str(sessions[pos-1].date())
                or price.get("price_coordinate") != "RAW_CLOSE"
                or price.get("quantity_coordinate") != RAW_OLD_SHARE_COORDINATE):
            raise ValueError("PRE_EX_RAW_CLOSE_IDENTITY_OR_UNIT_MISMATCH")
        _sha(price.get("source_fingerprint"), "raw_close")
        amount, close = facts["cash_per_raw_share"], price["raw_close"]
        if (any(isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) or v <= 0 for v in (amount, close))
                or amount / close >= SPEC["small_cash_fraction_strict_upper_bound"]):
            raise ValueError("NORMAL_SMALL_CASH_FRACTION_UNBOUND")
        observations = facts["issuer_history_ex_dates"]
        if not isinstance(observations, list) or any(not isinstance(v, str) for v in observations):
            raise ValueError("ISSUER_HISTORY_OBSERVATIONS_REQUIRED")
        result.update(status=("QUALIFIED_RESEARCH_FROZEN_CASH_FACT" if frozen_fact_scope else "ADJUDICATED_RESEARCH_EX_DATE"), ex_date=str(ex.date()),
            rule_key=rule_key, rule=copy.deepcopy(rule),
            calendar_binding=copy.deepcopy(calendar_binding),
            issuer_history_ex_dates=copy.deepcopy(observations),
            source_disagreement_preserved=any(v != str(ex.date()) for v in observations),
            issuer_error_acknowledged=False, exact_exchange_event_notice_obtained=False,
            historical_exchange_receipt_proven=False, broker_payment_proven=False,
            small_cash_fraction=amount/close,
            due_bill_evidence_status="NO_INDICATORS_IN_BOUND_SOURCES_NOT_PROOF_OF_ABSENCE",
            late_notice_evidence_status="NO_INDICATORS_IN_BOUND_SOURCES_NOT_EXCHANGE_RECEIPT_PROOF",
            first_tplus1_same_day_record="2024-05-29", reason=None,
            ex_date_provenance_role=(derived_role if source_scope in ("FROZEN_PRE2026_NYSE_COMMON_USD", "FROZEN_PRE2026_LATE_CURRENCY_NYSE_COMMON_USD") and facts.get("ex_date_provenance_role") == derived_role else "NAMED_VENDOR_EX_DATE_MATCHED_NORMAL_RULE"))
        if cns_record is not None:
            result.update(cns_bank_holiday_record_binding=copy.deepcopy(cns_record),
                published_record_date=facts["record_date"],cns_projected_record_date=cns_record["cns_projected_record_date"],
                ex_date_provenance_role=NSCC_CNS_RECORD_RESEARCH_ROLE,
                historical_availability_authority="UNKNOWN",exchange_notice_authority="UNKNOWN",
                actual_exchange_ex_authority="UNKNOWN",strict_PIT=False,quote_qualified=False,certified_NAV=False)
        if frozen_fact_scope:
            result.update(ex_date_provenance_role=expected_ex_role,
                historical_availability_authority="UNKNOWN",exchange_notice_authority="UNKNOWN",
                actual_exchange_ex_authority="UNKNOWN",cash_evidence_role=binding["cash_evidence_role"])
    except (KeyError, ValueError, TypeError, AttributeError, IndexError) as exc:
        result["reason"] = str(exc) or type(exc).__name__
    return result


def _terms(payload, *, allow_ads=False):
    if "id" in payload:
        if payload.get("security_type", "COMMON_STOCK") != "COMMON_STOCK":
            raise ValueError("ADS_COMMON_SHARE_SCHEMA_AMBIGUOUS")
        ticker = payload["listing_identity"].split(":")[1]
        amount = payload["cash_per_common_share"]
        available = payload["availability_bound"]["available_at"]
        if payload.get("cash_is_gross_announced_amount") is not True:
            raise ValueError("CASH_GROSS_UNIT_NOT_CONFIRMED")
        if payload.get("currency_basis") not in ("INFERRED_USD_CONTEXT", "EXPLICIT_USD"):
            raise ValueError("USD_CONTEXT_NOT_BOUND")
        return dict(key=payload["id"], ticker=ticker, issuer=payload["issuer"], security_type="COMMON_STOCK",
                    listing=payload["listing_identity"], amount=amount, record=payload["record_date"],
                    pay=payload["pay_date"], publication=payload["publication_date"], available=available,
                    candidate_ex=payload["candidate_ex_date"], currency_basis=payload["currency_basis"],
                    unit_basis=("ANNOUNCED_PER_COMMON_RAW_SHARE_EXPLICIT_USD" if payload["currency_basis"] == "EXPLICIT_USD" else "ANNOUNCED_PER_COMMON_RAW_SHARE_FROM_US_ISSUER_CONTEXT"))
    security_type = payload.get("security_type")
    if security_type not in ("COMMON_STOCK", "AMERICAN_DEPOSITARY_SHARE") or payload.get("amount_unit") != USD_PER_RAW_OLD_SHARE or payload.get("quantity_coordinate") != RAW_OLD_SHARE_COORDINATE:
        raise ValueError("COMMON_SHARE_CASH_COORDINATE_NOT_BOUND" if security_type == "COMMON_STOCK" else "RAW_SECURITY_CASH_COORDINATE_NOT_BOUND")
    if security_type == "AMERICAN_DEPOSITARY_SHARE" and allow_ads is not True:
        raise ValueError("ADS_EXPLICIT_OPT_IN_REQUIRED")
    if payload.get("currency_confidence") not in ("INFERRED_USD", "EXPLICIT_USD"):
        raise ValueError("USD_CONTEXT_NOT_BOUND")
    if security_type == "AMERICAN_DEPOSITARY_SHARE":
        amount = payload["cash_per_raw_ex_pretrade_ads"]
        unit = payload.get("ads_unit_evidence", {})
        if (payload.get("cash_per_raw_ex_pretrade_common_share") is not None
                or unit.get("unit_status") != "SOURCE_DECLARED_PER_ADS"
                or unit.get("source_unit") != "USD_PER_ADS_GROSS_BEFORE_APPLICABLE_FEES"
                or unit.get("cash_per_raw_ads") != amount
                or unit.get("source_reference") != payload["source_url"]):
            raise ValueError("ADS_CASH_UNIT_NOT_DIRECTLY_BOUND")
        # Validate a source-declared ratio; never synthesize a missing per-ADS cash
        # amount from an ordinary-share value or apply the ratio to ADS positions.
        ratio = unit.get("ordinary_shares_per_ads")
        ordinary = unit.get("cash_per_raw_ordinary_share_usd")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("ADS_ORDINARY_SHARE_RATIO_NOT_BOUND")
        if (isinstance(ordinary, bool) or not isinstance(ordinary, (int, float))
                or not math.isfinite(ordinary) or ordinary < 0
                or not math.isclose(amount, ordinary * ratio, rel_tol=1e-12, abs_tol=1e-12)):
            raise ValueError("ADS_ORDINARY_AMOUNT_RATIO_CONFLICT")
    else:
        amount = payload["cash_per_raw_ex_pretrade_common_share"]
    split = payload.get("split_unit_evidence")
    if split is not None and (split.get("cash_basis_for_ex_" + payload["record_date"].replace("-", "_")) != "POST_SPLIT_RAW_COMMON_SHARE" or split.get("issuer_declared_post_split_dividend") != amount):
        raise ValueError("SPLIT_CASH_UNIT_CONFLICT")
    return dict(key=payload["event_key"], ticker=payload["ticker"], issuer=payload["issuer"], security_type=security_type,
                listing=payload["listed_exchange"] + ":" + payload["ticker"], amount=amount,
                record=payload["record_date"], pay=payload["scheduled_pay_date"],
                publication=payload["publication_date"], available=payload["available_at_upper_bound"],
                candidate_ex=payload["ex_date_binding"]["value"],
                currency_basis=payload["currency_confidence"], unit_basis=("SOURCE_DIRECT_PER_RAW_ADS_GROSS; NO_ORDINARY_SHARE_FALLBACK_OR_QUANTITY_MULTIPLIER" if security_type == "AMERICAN_DEPOSITARY_SHARE" else "EXPLICIT_RAW_EX_PRETRADE_COMMON_SHARE; NO_SPLIT_MULTIPLICATION"))


def _identity(terms, entry, ex_open):
    identity = {k: entry[k] for k in ("security_id", "identity_kind", "issuer", "ticker", "listing_identity", "security_type")}
    if entry.get("identity_payload_sha256") != _hash(identity):
        raise ValueError("UNBOUND_SECURITY_IDENTITY_PAYLOAD")
    if any(entry[k] != terms[k] for k in ("issuer", "ticker")) or entry["listing_identity"] != terms["listing"] or entry["security_type"] != terms["security_type"]:
        raise ValueError("ISSUER_COMMON_CLASS_TICKER_IDENTITY_MISMATCH")
    if not entry.get("source_reference"):
        raise ValueError("IDENTITY_SOURCE_REFERENCE_REQUIRED")
    _sha(entry.get("source_fingerprint"), "security_identity")
    if _aware(entry.get("available_at"), "security_identity") > ex_open:
        raise ValueError("LATE_SECURITY_IDENTITY")
    sid = entry["security_id"]
    if not isinstance(sid, str) or not sid or sid.upper().startswith("FROZEN_VENDOR:") or any(t in sid.upper() for t in ("UNKNOWN", "NOT_EXTRACTED", "UNCONFIRMED", "NOT_REQUIRED")):
        raise ValueError("PLACEHOLDER_SECURITY_ID_FORBIDDEN")
    if entry["identity_kind"] == "SOURCE_DERIVED_ISSUER_COMMON_CLASS":
        if sid != source_derived_security_id(terms["issuer"], terms["ticker"], terms["listing"], terms["security_type"]):
            raise ValueError("SOURCE_DERIVED_STABLE_ID_MISMATCH")
    elif entry["identity_kind"] != "ACCEPTED_PIT_SECURITY_ID":
        raise ValueError("SECURITY_ID_AUTHORITY_UNKNOWN")
    return sid, {"identity": identity, "identity_payload_sha256": _hash(identity),
                 "source_reference": entry["source_reference"], "source_fingerprint": entry["source_fingerprint"],
                 "available_at": str(_aware(entry["available_at"], "security_identity")), "CUSIP_claim": False}


def bind_cash_entitlements(fact_projections, *, calendar, calendar_binding,
                           unsupported_events, security_bindings, pre_ex_raw_closes, rule_sources,
                           cash_event_classification=None, allow_ads=False, source_precedence_policy=None):
    """Pure bounded binder. Blocked/unmapped vendor events survive unchanged."""
    precedence = validate_source_precedence_policy(source_precedence_policy)
    sessions = tuple(_day(d, "calendar") for d in calendar)
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("LEGAL_CALENDAR_UNIQUE_SORTED_REQUIRED")
    if calendar_binding.get("status") != "SOURCE_BOUND_LEGAL_SESSION_CALENDAR" or calendar_binding.get("session_dates_sha256") != _hash([str(d.date()) for d in sessions]):
        raise ValueError("UNBOUND_LEGAL_SESSION_CALENDAR")
    _sha(calendar_binding.get("source_fingerprint"), "calendar")
    if not calendar_binding.get("source_reference"):
        raise ValueError("CALENDAR_SOURCE_REFERENCE_REQUIRED")
    rules = _rules(rule_sources)
    original = tuple(copy.deepcopy(tuple(unsupported_events)))
    prepared = []; blocked = []
    for index, envelope in enumerate(fact_projections):
        key = str(envelope.get("payload", {}).get("id", envelope.get("payload", {}).get("event_key", index)))
        try:
            payload, guard = _guard(envelope); t = _terms(payload, allow_ads=allow_ads)
            if payload.get("currency") != "USD" or not payload.get("source_url", "").startswith("https://"):
                raise ValueError("OFFICIAL_USD_SOURCE_CONTEXT_REQUIRED")
            amount = t["amount"]
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
                raise ValueError("FINITE_NONNEGATIVE_CASH_AMOUNT_REQUIRED")
            record = _day(t["record"], "record_date"); pay = _day(t["pay"], "pay_date", known_future_schedule=True); publication = _day(t["publication"], "publication_date")
            # Frozen compatibility: May-28's original coordinate is retained.
            # New source consumers use the explicit NYSE transition policy.
            ex, rule_key = normal_cash_ex_date(record, sessions,
                scope_end_exclusive=SPEC["calendar_end_exclusive"],
                policy="FROZEN_PRE2026_LEGACY")
            if sessions.index(ex) == 0: raise ValueError("PRE_EX_CLOSE_SESSION_MISSING")
            prior = sessions[sessions.index(ex)-1]; ex_open = _clock(ex, 9, 30)
            if _day(t["candidate_ex"], "candidate_ex") != ex:
                raise ValueError("CALLER_VENDOR_EX_DISAGREES_WITH_NORMAL_DIV_ASSUMPTION")
            available = _aware(t["available"], "publication_upper_bound")
            if available < publication.tz_localize("UTC") or available >= ex_open:
                raise ValueError("LATE_OR_INCONSISTENT_PUBLICATION")
            if not ex <= record <= pay: raise ValueError("DUE_BILL_OR_DATE_ORDER_UNSUPPORTED")
            sid, identity = _identity(t, security_bindings[t["ticker"]], ex_open)
            price = pre_ex_raw_closes[t["key"]]
            if price.get("ticker") != t["ticker"] or price.get("security_id") != sid or price.get("price_coordinate") != "RAW_CLOSE" or price.get("quantity_coordinate") != RAW_OLD_SHARE_COORDINATE:
                raise ValueError("PRE_EX_RAW_CLOSE_IDENTITY_OR_UNIT_MISMATCH")
            if _day(price.get("signal_date"), "pre_ex_raw_close") != prior or _aware(price.get("available_at"), "pre_ex_raw_close") > _clock(prior, 16):
                raise ValueError("PRE_EX_CLOSE_NOT_SIGNAL_KNOWN_PRIOR_SESSION")
            _sha(price.get("source_fingerprint"), "raw_close")
            close = price.get("raw_close")
            if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
                raise ValueError("POSITIVE_FINITE_RAW_CLOSE_REQUIRED")
            if amount / close >= SPEC["small_cash_fraction_strict_upper_bound"]:
                raise ValueError("LARGE_CASH_DUE_BILL_NOT_SUPPORTED")
            event = SourceBackedEntitlementEvent("SOURCE_CASH:" + _hash({"security_id": sid, "ex": str(ex.date()), "family": "CASH_DIVIDEND"}), "CASH_DIVIDEND", sid, t["ticker"], str(ex.date()), str(record.date()), str(pay.date()), str(available), float(amount), "USD", USD_PER_RAW_OLD_SHARE, RAW_OLD_SHARE_COORDINATE, "TIER1_ISSUER_REGULATOR_EXCHANGE", payload["source_url"], guard["sha256"])
            proof = {"fact_key": t["key"], "projection": guard, "identity": identity,
                     "source_reference": payload["source_url"], "cash_per_raw_old_share": amount,
                     "currency_basis": t["currency_basis"], "amount_unit_basis": t["unit_basis"],
                     "ex_assumption": {"status": "RESEARCH_NORMAL_SMALL_CASH_EXPECTED_EX_NOT_DIRECT_ISSUER_DECLARATION", "value": event.ex_date, "rule": rules[rule_key], "calendar_binding": copy.deepcopy(calendar_binding)},
                     "publication_upper_bound": event.available_at, "exchange_received_notice": "INFERRED_FROM_EARLY_OFFICIAL_PUBLICATION; NOT_VERIFIED", "broker_payment": "NOT_OBSERVED",
                     "pay_date_status": "ANNOUNCED_EXPECTED_SCHEDULE; FIRST_LEGAL_OPEN_ON_OR_AFTER", "raw_source_bytes_available": payload.get("raw_bytes_available", False), "raw_source_sha256": payload.get("raw_sha256"),
                     "small_cash_predicate": {"strict_fraction_upper_bound": 0.25, "fraction": amount/close, "price_binding": copy.deepcopy(price)}, "event_fingerprint": event.event_fingerprint}
            if t["security_type"] == "AMERICAN_DEPOSITARY_SHARE":
                proof["ads_unit_evidence"] = copy.deepcopy(payload["ads_unit_evidence"])
                proof["cash_deductions"] = copy.deepcopy(payload.get("cash_deductions", {"depositary_fees": "UNKNOWN", "withholding": "UNKNOWN", "actual_broker_cash": "NOT_OBSERVED"}))
                proof["gross_cash_basis"] = "ANNOUNCED_PER_RAW_ADS_BEFORE_DEDUCTIONS; NO_FEE_OR_WITHHOLDING_ESTIMATE"
            if precedence is not None and event.ticker=="XP" and event.ex_date=="2023-09-11":
                proof["source_precedence_fact"]=dict(
                    original_statement_source_sha256=envelope.get("original_statement_source_sha256"),
                    security_class=payload.get("security_class"))
            prepared.append((event, proof))
        except (KeyError, ValueError, TypeError, AttributeError, IndexError) as exc:
            blocked.append({"fact_key": key, "reason": str(exc) or type(exc).__name__, "vendor_events_retained": True})
    counts = {}
    for event, _ in prepared: counts[event.event_id] = counts.get(event.event_id, 0) + 1
    good = []
    for event, proof in prepared:
        if counts[event.event_id] != 1:
            blocked.append({"fact_key": proof["fact_key"], "reason": "DUPLICATE_OR_REVISED_ECONOMIC_EVENT_NOT_RESOLVED", "vendor_events_retained": True})
        else: good.append((event, proof))
    ticker_ids = {}; bad_tickers = set()
    for event, _ in good:
        if event.ticker in ticker_ids and ticker_ids[event.ticker] != event.old_security_id: bad_tickers.add(event.ticker)
        ticker_ids[event.ticker] = event.old_security_id
    if len(set(ticker_ids.values())) != len(ticker_ids): raise ValueError("SECURITY_TICKER_BIJECTION_REQUIRED")
    if bad_tickers: raise ValueError("SECURITY_TICKER_BINDING_CHANGED_WITHIN_CATALOGUE")
    valid = {(event.ticker, event.ex_date): event for event, _ in good}
    valid_proofs = {(event.ticker,event.ex_date): proof for event,proof in good}
    precedence_applied=[]
    remove = set(); remaining = []; removed_classifications = []
    classifications = cash_event_classification or {}
    vendor_key_counts = {}
    for item in original:
        try:
            k = (item.get("ticker"), str(_day(item.get("effective_date"), "vendor_effective_date").date()), _sha(item.get("source_fingerprint"), "vendor_event"))
            vendor_key_counts[k] = vendor_key_counts.get(k, 0) + 1
        except (ValueError, TypeError):
            continue
    for item in original:
        try:
            day = str(_day(item.get("effective_date"), "vendor_effective_date").date())
            fp = _sha(item.get("source_fingerprint"), "vendor_event")
            key = (item.get("ticker"), day, fp)
            # A three-field removal key cannot distinguish independent same-key
            # forensic/noncash records. Preserve all records under ambiguous keys.
            if vendor_key_counts.get(key, 0) != 1:
                remaining.append(item); continue
            classification = classifications.get(key)
            event = valid.get(key[:2])
            if not isinstance(classification, dict) or event is None:
                remaining.append(item); continue
            if (classification.get("family") not in ("CASH_DIVIDEND", "CASH_DISTRIBUTION")
                    or classification.get("vendor_event_source_fingerprint") != fp
                    or classification.get("statement_fact_sha256") != event.source_fingerprint
                    or classification.get("non_cash_flags_absent") is not True
                    or classification.get("amount_unit") != USD_PER_RAW_OLD_SHARE
                    or classification.get("quantity_coordinate") != RAW_OLD_SHARE_COORDINATE):
                remaining.append(item); continue
            equal_amount=classification.get("vendor_cash_per_raw_old_share")==event.cash_per_old_share
            use_precedence=(not equal_amount and precedence is not None and
                _source_precedence_matches(precedence,event,valid_proofs[key[:2]],classification,
                                           security_bindings[event.ticker],item))
            if not equal_amount and not use_precedence:
                remaining.append(item); continue
            _sha(classification.get("classification_source_fingerprint"), "cash_classification")
            _sha(classification.get("vendor_typed_cash_field_source_sha256"), "vendor_cash_fields")
            # Same-day forensic diagnostics are independent of this cash event.
            if item.get("reason") == "RAW_LARGE_MOVE_DIAGNOSTIC":
                remaining.append(item); continue
            remove.add(key)
            if use_precedence:
                precedence_applied.append(dict(key=key,qualification_basis="SOURCE_DECLARED_GROSS",
                    issuer_cash_per_raw_old_share=event.cash_per_old_share,
                    vendor_cash_per_raw_old_share=classification["vendor_cash_per_raw_old_share"],
                    vendor_numeric_conflict_reconciled=False,final_paid_rate_verified=False,
                    statement_fact_sha256=event.source_fingerprint,
                    vendor_typed_cash_field_source_sha256=classification["vendor_typed_cash_field_source_sha256"],
                    vendor_cash_field=classification["vendor_cash_field"],classification_exception_removed=True))
            removed_classifications.append({"key": key, "proof": copy.deepcopy(classification)})
            continue
        except (ValueError, TypeError):pass
        remaining.append(item)
    events = tuple(event for event, _ in sorted(good, key=lambda x: (x[0].ex_date, x[0].event_id)))
    security_tickers = {event.old_security_id: event.ticker for event in events}
    proofs = tuple(proof for _, proof in good)
    manifest = {"spec": SPEC, "proofs": proofs, "blocked": blocked, "removal_keys": sorted(remove), "security_tickers": security_tickers,
                "cash_classifications_removed": removed_classifications, "ambiguous_vendor_keys_preserved": [k for k,v in vendor_key_counts.items() if v>1], "unsupported_catalogue_payload_sha256": _hash(original),
                "physical_bytes_guard_owner": "caller; binder reads no files", "coverage": "ONLY_EXACT_BOUND_EVENTS; NOT_FULL848_OR_BROKER_PAYMENT_PROOF"}
    if allow_ads is True:
        manifest["ads_opt_in"] = "SOURCE_DECLARED_PER_RAW_ADS_GROSS; CLASS_SEPARATE; DEDUCTIONS_NOT_ESTIMATED"
    if precedence is not None:
        manifest["source_precedence"]=dict(precedence,numeric_conflict_diagnostics=precedence_applied,
            policy_applied=bool(precedence_applied),scope="ONLY_EXACT_XP_CASH_CLASSIFICATION; NO_SHARE_TRANSFORM_OR_OTHER_UNKNOWN_REMOVAL")
    source_binding = {"status": "SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND", "source_fingerprint": _hash(manifest), "quantity_coordinate": RAW_OLD_SHARE_COORDINATE,
                      "event_fingerprints": [event.event_fingerprint for event in events], "security_tickers": security_tickers, "manifest": manifest}
    return CashBindingResult(events, security_tickers, source_binding, tuple(sorted(remove)), tuple(remaining), proofs, tuple(blocked))
