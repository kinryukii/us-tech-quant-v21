"""Source/account descendant for the existing reused policy pair.

Reuse canonical source terms, identity and normal-ex-date validators; retain the
original private typed class and accounting lifecycle. Issuer cash is independent
of vendor affine price transforms. This module reads only explicitly pinned
pre2026 source projections, never predictions, accounts or candidate economics.
"""
from __future__ import annotations
from dataclasses import asdict, fields
import copy
import hashlib
import json
import math
import re
from pathlib import Path
import pandas as pd
from scripts.research.a2.data import joint_cash_bindings as cash

SCHEMA = "B_CA_SOURCE_ACCOUNT_DESCENDANT_V1"
CLOCK = "ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION"

SOURCE_DECLARED_ADS_CASH_SCOPE = dict(
    task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1",
    scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
    clock_role="SOURCE_DECLARED_PRE_EX_RESEARCH_ACCOUNTING_ONLY",
    accounting_clock_convention=CLOCK,
    scope_start="2023-01-01", scope_end_exclusive="2026-01-01",
    security_type="AMERICAN_DEPOSITARY_SHARE",
    amount_basis="SOURCE_DIRECT_PER_RAW_ADS_GROSS_BEFORE_APPLICABLE_DEDUCTIONS",
    ordinary_share_ratio_role="SOURCE_VALIDATION_ONLY_NO_POSITION_MULTIPLIER",
    net_cash_and_depositary_fee_authority="UNKNOWN_NOT_ESTIMATED",
    strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False)


SOURCE_DECLARED_CASH_EX_SCOPE = dict(
    task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1",
    scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
    clock_role="SOURCE_DECLARED_PRE_EX_RESEARCH_ACCOUNTING_ONLY",
    accounting_clock_convention=CLOCK,
    scope_start="2023-01-01", scope_end_exclusive="2026-01-01",
    ex_coordinate="EXACT_ISSUER_DECLARED_DATE_IN_UNCHANGED_FROZEN_TRADING_CALENDAR",
    record_coordinate="ORIGINAL_LITERAL_PRESERVED_INCLUDING_NONTRADING_RECORD",
    missing_ex_authority="BLOCKED_NO_CALENDAR_INSERTION_OR_UPC_INFERENCE",
    strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False)


def _hash(value):
    return hashlib.sha256(cash.canonical_bytes(value)).hexdigest()


def _pin(ref):
    path = Path(ref["path"])
    if path.drive.upper() != "D:":
        raise ValueError("CA_SOURCE_OUTSIDE_APPROVED_D_ROOT")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != ref["sha256"]:
        raise ValueError("CA_SOURCE_PHYSICAL_BYTES_CHANGED:" + str(path))
    return path


def _read(ref):
    return json.loads(_pin(ref).read_text(encoding="utf-8-sig"))


def _key(item):
    result = dict(item)
    result["effective_date"] = str(cash._day(result["effective_date"], "original_event").date())
    return _hash(result)


def classify_existing_cash(original_events):
    """Derive old ordinary-clock applicability from the pinned source chain.

    Old special-precedence bodies remain unopened. Caller classifications cannot
    waive explicit regular/quarterly evidence or manufacture it from a label.
    """
    original = tuple(original_events.get("entitlement_events", ()))
    proof_rows = original_events["entitlement_source_binding"]["manifest"]["proofs"]
    proofs = {p["event_fingerprint"]: p for p in proof_rows}
    if len(proofs) != len(proof_rows) or len({e.event_fingerprint for e in original}) != len(original):
        raise ValueError("CA_EXISTING_SOURCE_PROOF_NOT_UNIQUE")
    fields = ("title", "description", "dividend_type", "source_excerpt")
    rows = []
    for event in original:
        row = dict(event_fingerprint=event.event_fingerprint,
                   status="LEGACY_NOT_RECLASSIFIED", evidence_ref=None,
                   evidence_field=None, evidence_text=None,
                   reason="ORDINARY_CLASS_NOT_PROVEN")
        if event.action_type != "CASH_DIVIDEND" or event.ticker == "MKFG":
            row["reason"] = "OUTSIDE_VERIFIED_ORDINARY_CASH_SCOPE"
            rows.append(row)
            continue
        if event.event_fingerprint not in proofs:
            raise ValueError("CA_EXISTING_SOURCE_PROOF_MISSING")
        norm_ref = proofs[event.event_fingerprint]["projection"]
        norm = _read(norm_ref)
        if "source_precedence_fact" in norm:
            row.update(evidence_ref=norm_ref,
                       reason="SOURCE_PRECEDENCE_PRESERVED_UNRECLASSIFIED")
            rows.append(row)
            continue
        evidence_ref = norm.get("original_source_projection", norm_ref)
        evidence = norm if evidence_ref == norm_ref else _read(evidence_ref)
        texts = [(field, evidence[field]) for field in fields
                 if isinstance(evidence.get(field), str) and evidence[field].strip()]
        excluded = next(((field, text) for field, text in texts
                         if re.search(r"\bspecial\b|\bliquidat\w*|\bmerger\w*", text, re.I)), None)
        regular = next(((field, text) for field, text in texts
                        if re.search(r"\b(?:quarterly|regular)\b", text, re.I)), None)
        selected = excluded or regular or (texts[0] if texts else (None, None))
        row.update(evidence_ref=evidence_ref, evidence_field=selected[0],
                   evidence_text=selected[1])
        if excluded:
            row["reason"] = "NONORDINARY_SOURCE_TEXT"
        elif regular:
            row.update(status="SOURCE_CLASS_VERIFIED_ORDINARY",
                       reason="EXPLICIT_REGULAR_OR_QUARTERLY_SOURCE_TEXT")
        rows.append(row)
    return rows


def rebind_entitlement_catalogue(original_events, *, source_owner, target_owner):
    """Lossless declared typed-namespace transport, never event reconstruction.

    Quantity corporate actions and all source bindings remain byte-for-byte
    semantic objects. Unknown/custom cash types stop rather than being guessed.
    """
    names=("SourceBackedEntitlementEvent","SourceBackedTerminalEvent","SourceBackedTerminalSettlement")
    def convert(event):
        name=next((name for name in names if type(event) is getattr(source_owner,name,None)),None)
        if name is None:
            raise ValueError("CA_DECLARED_LEGACY_TYPED_CLASS_REQUIRED")
        target=getattr(target_owner,name)
        if [f.name for f in fields(event)]!=[f.name for f in fields(target)]:
            raise ValueError("CA_LEGACY_TYPED_FIELD_LAYOUT_CHANGED")
        value=asdict(event)
        if name=="SourceBackedTerminalEvent" and event.settlement is not None:
            value["settlement"]=convert(event.settlement)
        result=target(**value)
        if (asdict(result)!=asdict(event)
                or source_owner.canonical_bytes(asdict(event))!=target_owner.canonical_bytes(asdict(result))
                or (hasattr(event,"event_fingerprint") and event.event_fingerprint!=result.event_fingerprint)):
            raise ValueError("CA_LEGACY_TYPED_IDENTITY_OR_COMMITMENT_CHANGED")
        return result
    result=dict(original_events)
    result["entitlement_events"]=tuple(convert(e) for e in original_events.get("entitlement_events",()))
    return result


POST_VERIFIED_SCOPE=dict(scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
    task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1",clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
    accounting_clock_convention=CLOCK,scope_start="2023-01-01",scope_end_exclusive="2026-01-01",
    strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)


ISSUER_PDF_PROFILE="ISSUER_HOSTED_ORIGINAL_PDF_WITH_EXACT_HISTORICAL_IR_METADATA"
ISSUER_PDF_SCOPE=dict(POST_VERIFIED_SCOPE,source_transport_profile=ISSUER_PDF_PROFILE,
    cash_evidence_role="EXPLICIT_ORIGINAL_ISSUER_PDF_COMMON_CASH_AND_SUBJECT_CUSIP_RAW_NAMESPACE",
    currency_authority="INFERRED_USD_SAME_PDF_US_GEOGRAPHIC_COMMON_DOLLAR_CONTEXT",
    ex_coordinate_role="DERIVED_NYSE_NORMAL_EX_FROM_RECORD_DATE_MATCHED_EXACT_FROZEN_EVENT",
    historical_availability_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN")


def _issuer_pdf_cash_terms(payload,entry,*,source_ref_transport=()):
    """Dated issuer PDF clause, explicit common cash and original frozen CUSIP; no HTML/header fiction."""
    from decimal import Decimal
    from scripts.storage.refresh_sec_event_originals import FilingText,load_pdf_package
    flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
    facts=copy.deepcopy(payload["source_projection"]);exact=payload["exact_original_unsupported_keys"]
    if (payload.get("schema")!="B_FROZEN_HISTORY_POST_VERIFIED_CASH_SOURCE_PROJECTION_V1"
            or payload.get("source_scope")!="FROZEN_PRE2026_NYSE_COMMON_USD"
            or payload.get("source_transport_profile")!=ISSUER_PDF_PROFILE
            or payload.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY"
            or payload.get("historical_available_at") is not None
            or payload.get("exchange_notice_authority")!="UNKNOWN" or payload.get("actual_exchange_ex_authority")!="UNKNOWN"
            or payload.get("source_declared_ex_date") is not None
            or any(facts.get(k) not in (None,"UNKNOWN") for k in ("exchange_notice_authority","actual_exchange_ex_authority","historical_availability_authority"))
            or any(payload.get(k) is not False for k in flags)
            or facts.get("available_at") is not None or facts.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY"
            or facts.get("security_type")!="COMMON_STOCK" or facts.get("currency")!="USD"
            or facts.get("amount_unit")!=cash.USD_PER_RAW_OLD_SHARE or facts.get("quantity_coordinate")!=cash.RAW_OLD_SHARE_COORDINATE
            or facts.get("ordinary_cash_confirmed") is not True or facts.get("noncash_flags_absent") is not True
            or facts.get("special_or_due_bill_indicator") is not False or facts.get("late_notice_indicator") is not False
            or payload.get("identity_binding")!=entry["identity_binding"] or payload.get("prior_raw_close")!=entry["prior_raw_close"]
            or len(exact)!=1 or exact!=entry["original_unsupported_keys"] or facts.get("exact_frozen_event_key")!=exact[0]
            or facts.get("ex_date_provenance_role")!=ISSUER_PDF_SCOPE["ex_coordinate_role"]):
        raise ValueError("CA_ISSUER_PDF_EXACT_ACCOUNTING_SUBJECT_REQUIRED")
    refs=payload["source_refs"]
    def pinned(ref):
        if sum(ref==item for item in refs)!=1:raise ValueError("CA_ISSUER_PDF_NESTED_SOURCE_PIN_REQUIRED")
        target=next((tx["custody_ref"] for tx in source_ref_transport if ref==tx["original_ref"]),ref)
        return _pin(target)
    normalized=lambda text:" ".join(text.split())
    typed=lambda text:hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    source_ref=payload["issuer_pdf_cash_source_custody_ref"];source=json.loads(pinned(source_ref).read_text(encoding="utf-8-sig"))
    if (source.get("schema")!="ISSUER_HOSTED_ORIGINAL_HISTORICAL_PDF_CASH_SOURCE_CUSTODY_V1"
            or source.get("source_role")!="ISSUER_DISTRIBUTED_ORIGINAL_RELEASE_INDEPENDENT_PUBLIC_SOURCE"
            or source.get("actual_HTTP_status")!=200 or source.get("PDF_original_byte_range") is not None
            or source.get("historical_available_at") is not None or source.get("historical_availability_authority")!="UNKNOWN"
            or source.get("private_board_date") is not None or source.get("ticker")!=facts["ticker"]
            or any(source.get(k) is not False for k in flags)):
        raise ValueError("CA_ISSUER_PDF_HONEST_ORIGINAL_TRANSPORT_REQUIRED")
    body=pinned(source["original_HTTP_ref"])
    if body.stat().st_size!=source["original_HTTP_bytes"]:raise ValueError("CA_ISSUER_PDF_ORIGINAL_BYTE_COUNT_CHANGED")
    reader_type,extractor=load_pdf_package(payload["pdf_extractor"]["path"])
    if extractor!=payload["pdf_extractor"]:raise ValueError("CA_ISSUER_PDF_PINNED_EXTRACTOR_REQUIRED")
    page_index=source["source_pdf_page_index"]
    if type(page_index) is not int or page_index<0:raise ValueError("CA_ISSUER_PDF_BOUNDED_PAGE_REQUIRED")
    with body.open("rb") as stream:
        reader=reader_type(stream)
        if len(reader.pages)!=source["PDF_page_count"] or page_index>=len(reader.pages):raise ValueError("CA_ISSUER_PDF_BOUNDED_PAGE_REQUIRED")
        page=reader.pages[page_index].extract_text()
    saved=pinned(source["page_visible_text_ref"]).read_bytes().decode("utf-8-sig")
    if saved not in (page,page+"\n") or typed(page)!=source["page_visible_text_typed_content_sha256"]:
        raise ValueError("CA_ISSUER_PDF_ORIGINAL_PAGE_PROJECTION_CHANGED")
    def span_text(span):
        if (not isinstance(span,list) or len(span)!=2 or any(type(v) is not int for v in span)
                or not 0<=span[0]<span[1]<=len(page) or span[1]-span[0]>65536):
            raise ValueError("CA_ISSUER_PDF_EXACT_PROJECTED_CHARACTER_RANGE_REQUIRED")
        return page[span[0]:span[1]]
    literal=span_text(source["cash_fragment_PDF_projected_page_character_range"])
    utf8_span=source["cash_fragment_PDF_projected_UTF8_byte_range"];encoded=page.encode("utf-8")
    if (not isinstance(utf8_span,list) or len(utf8_span)!=2 or any(type(v) is not int for v in utf8_span)
            or not 0<=utf8_span[0]<utf8_span[1]<=len(encoded) or encoded[utf8_span[0]:utf8_span[1]]!=literal.encode("utf-8")
            or pinned(source["original_cash_text_fragment_ref"]).read_bytes().decode("utf-8-sig") not in (literal,literal+"\n")
            or normalized(literal)!=source["dividend_paragraph"] or typed(normalized(literal))!=source["dividend_paragraph_typed_content_sha256"]
            or pinned(source["text_projection_ref"]).read_bytes().decode("utf-8-sig") not in (normalized(literal),normalized(literal)+"\n")):
        raise ValueError("CA_ISSUER_PDF_CHARACTER_UTF8_AND_CASH_LITERAL_CHANGED")
    publication=source["publication_original_fragment"]
    pub=cash._day(source["source_publication_date"],"issuer_pdf_publication")
    if (publication.get("page_index")!=page_index or span_text(publication["projected_character_range"])!=publication["visible_text"]
            or publication["visible_text"]!=str(pub.date()) or not pd.Timestamp("2023-01-01")<=pub<pd.Timestamp("2026-01-01")):
        raise ValueError("CA_ISSUER_PDF_ORIGINAL_PUBLICATION_LITERAL_CHANGED")
    locator=json.loads(pinned(source["source_locator_ref"]).read_text(encoding="utf-8-sig"))
    params=locator.get("request_parameters",{});rows=locator.get("rows",[])
    if (locator.get("actual_HTTP_status")!=200 or locator.get("news_bodies_read") is not False
            or params.get("bodyType")!=0 or params.get("year")!=pub.year or not rows
            or any(pd.Timestamp(row["PressReleaseDate"]).year!=pub.year or row.get("Body") not in (None,"") for row in rows)):
        raise ValueError("CA_ISSUER_PDF_EXACT_PRE2026_METADATA_ONLY_LOCATOR_REQUIRED")
    metadata=json.loads(pinned(locator["original_HTTP_ref"]).read_text(encoding="utf-8-sig"))
    original_rows=metadata.get("GetPressReleaseListResult",[])
    if (not original_rows or any(pd.Timestamp(row["PressReleaseDate"]).year!=pub.year
            or row.get("Body") not in (None,"") or row.get("ShortBody") not in (None,"") for row in original_rows)):
        raise ValueError("CA_ISSUER_PDF_ORIGINAL_PRE2026_METADATA_ONLY_REQUIRED")
    columns=("DocumentPath","Headline","LinkToDetailPage","LinkToUrl","PressReleaseDate","PressReleaseId","SeoName")
    projected=[dict(**{k:row[k] for k in columns},validated_publication_date=str(pd.Timestamp(row["PressReleaseDate"]).date())) for row in original_rows]
    if projected!=rows:raise ValueError("CA_ISSUER_PDF_EXACT_ORIGINAL_LOCATOR_PROJECTION_CHANGED")
    selected=[row for row in rows if row.get("DocumentPath")==source["source_url"]]
    if (len(selected)!=1 or selected[0].get("validated_publication_date")!=str(pub.date())
            or pd.Timestamp(selected[0]["PressReleaseDate"]).normalize()!=pub
            or source.get("publication_time_in_official_metadata")!=str(pd.Timestamp(selected[0]["PressReleaseDate"]).time())
            or source.get("metadata_clock_timezone")!="UNKNOWN"):
        raise ValueError("CA_ISSUER_PDF_FILE_URL_AND_REAL_HEADER_DATE_CHANGED")
    expression=(r"(.+?), ([A-Za-z.]+)--\(BUSINESS WIRE\)-- (.+?) \(the .+?\) \(NYSE: ([A-Z][A-Z0-9.\-]*)\) today announced that its Board of Directors declared a regular quarterly cash dividend of \$([0-9]+(?:\.[0-9]+)?) per share of common stock to be paid on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), to stockholders of record on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})[.]")
    match=re.fullmatch(expression,normalized(literal))
    if match is None:raise ValueError("CA_ISSUER_PDF_EXPLICIT_REGULAR_COMMON_CASH_STATEMENT_REQUIRED")
    city,dateline_state,legal_name,symbol,amount_literal,pay,record=match.groups()
    us_literal=payload["same_file_US_context_literal"]
    us_match=re.fullmatch(re.escape(city.title())+r", ("+_US_CHARTER_STATE_NAMES+r")",us_literal)
    if (us_match is None or us_literal not in page or not us_match.group(1).casefold().startswith(dateline_state.rstrip(".").casefold())
            or facts.get("issuer_jurisdiction")!="US" or facts.get("listed_exchange_jurisdiction")!="US"
            or facts.get("exchange_rule_applicability")!="NYSE_LISTED_RAW_USD_COMMON_SHARE"
            or facts.get("exchange_listing_source_reference")!=source["original_HTTP_ref"]["path"]
            or facts.get("exchange_listing_source_fingerprint")!=source["original_HTTP_ref"]["sha256"]):
        raise ValueError("CA_ISSUER_PDF_SAME_FILE_US_COMMON_DOLLAR_CONTEXT_REQUIRED")
    amount=Decimal(amount_literal)
    if (not amount.is_finite() or amount<=0 or amount!=Decimal(str(facts["cash_per_raw_share"]))
            or facts["record_date"]!=str(pd.Timestamp(record).date()) or facts["pay_date"]!=str(pd.Timestamp(pay).date())
            or source.get("source_payment_date")!=facts["pay_date"] or facts.get("publication_calendar_date")!=str(pub.date())
            or facts.get("issuer_source_fingerprint")!=source["original_HTTP_ref"]["sha256"]
            or facts.get("identity_source_fingerprint")!=payload["frozen_account_identity_ref"]["sha256"]):
        raise ValueError("CA_ISSUER_PDF_EXACT_COMMON_AMOUNT_AND_DATES_CHANGED")
    frozen=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry["identity_binding"]["issuer"])
    if frozen is None:raise ValueError("CA_ISSUER_PDF_ORIGINAL_FROZEN_COM_REQUIRED")
    def fragment(item,body):
        span=item["original_byte_range"]
        if (not isinstance(span,list) or len(span)!=2 or any(type(v) is not int for v in span)
                or not 0<=span[0]<span[1]<=body.stat().st_size or span[1]-span[0]>65536):
            raise ValueError("CA_ISSUER_PDF_SUBJECT_ORIGINAL_BYTE_RANGE_REQUIRED")
        with body.open("rb") as stream:stream.seek(span[0]);part=stream.read(span[1]-span[0])
        raw=pinned(item["original_fragment_ref"]).read_bytes();parser=FilingText();parser.feed(raw.decode("utf-8"))
        text=normalized(" ".join(parser.parts));saved=pinned(item["text_projection_ref"]).read_bytes().decode("utf-8-sig")
        if raw!=part or text!=normalized(item["text"]) or saved not in (item["text"],item["text"]+"\n") or typed(item["text"])!=item["text_typed_content_sha256"]:
            raise ValueError("CA_ISSUER_PDF_SUBJECT_ORIGINAL_TEXT_CHANGED")
        return text
    # Reuse the original subject/CIK/CUSIP proof checker. Source MPW and the
    # original MPT raw coordinate are roles connected by this CUSIP, never aliases.
    id_ref,identity,title,subject_only=_source_subject_cusip_identity(payload,entry,frozen,legal_name,
        payload["source_subject_issuer_CIK"],{"name":re.sub(r"[.,]","",legal_name).upper()},pinned=pinned,fragment=fragment)
    if title!="Common Stock" or subject_only or not facts["listing_identity"].startswith("NYSE:"):
        raise ValueError("CA_ISSUER_PDF_EXACT_SUBJECT_COMMON_AND_RAW_VENUE_REQUIRED")
    for ref in refs:pinned(ref)
    binding=dict(status="PINNED_ORIGINAL_ISSUER_PDF_EXPLICIT_COMMON_CASH",source_transport_profile=ISSUER_PDF_PROFILE,
        original_PDF_ref=source["original_HTTP_ref"],source_cash_custody_ref=source_ref,
        source_legal_issuer_literal=legal_name,source_legal_listing_identity="NYSE:"+symbol,
        accounting_label_listing_identity=facts["listing_identity"],frozen_account_identity_binding=frozen,
        source_subject_CUSIP_custody_ref=id_ref,source_CUSIP=identity["raw_CUSIP_literal"],
        source_publication_date=str(pub.date()),source_publication_timezone="UNKNOWN",
        private_board_declaration_date=None,actual_HTTP_fetch_timestamp=source["actual_HTTP_fetch_timestamp"],
        custody_created_utc=source["custody_created_utc"],capture_is_not_available_at=True,
        currency_basis="INFERRED_USD_SAME_PDF_US_COMMON_DOLLAR_CONTEXT",source_currency_explicit_USD=False,
        source_declared_ex_date=None,actual_exchange_ex_authority="UNKNOWN",exchange_notice_authority="UNKNOWN",
        historical_availability_authority="UNKNOWN",available_at=None,ex_coordinate_role=ISSUER_PDF_SCOPE["ex_coordinate_role"],
        quantity_transform=False,new_member_or_buy_authority=False,ticker_alias_inferred=False,**{k:False for k in flags})
    facts["issuer_pdf_cash_binding"]=binding
    return dict(id="ISSUER_PDF_CASH_"+_hash(facts),issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",cash_per_common_share=float(amount),
        cash_is_gross_announced_amount=True,currency="USD",currency_basis="INFERRED_USD_CONTEXT",
        record_date=facts["record_date"],pay_date=facts["pay_date"],publication_date=str(pub.date()),
        candidate_ex_date=exact[0]["effective_date"],availability_bound=dict(available_at=None),ordinary_cash_dividend=True,
        source_url=source["source_url"],source_scope=payload["source_scope"],historical_ex_adjudication_input=facts,
        issuer_pdf_cash_binding=binding,frozen_account_identity_binding=frozen)


def _post_verified_terms(payload, entry, *, source_ref_transport=()):
    """Retain conflicting early and late issuer facts; do not splice source clocks."""
    if payload.get("source_transport_profile")==ISSUER_PDF_PROFILE:
        return _issuer_pdf_cash_terms(payload,entry,source_ref_transport=source_ref_transport)
    if (payload.get("schema")!="B_FROZEN_HISTORY_POST_VERIFIED_CASH_SOURCE_PROJECTION_V1"
            or payload.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY"
            or payload.get("historical_available_at") is not None
            or payload.get("original_record_year_conflict_preserved") is not True
            or any(payload.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
        raise ValueError("CA_POST_VERIFIED_SOURCE_ROLE_REQUIRED")
    facts=payload["source_projection"]
    early=payload["original_pre_ex_announcement"]; late=payload["later_issuer_history"]
    capture=cash._aware(late["archive_capture_utc"],"actual_late_capture")
    exact=payload["exact_original_unsupported_keys"]
    if (facts.get("available_at") is not None or facts.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY"
            or facts.get("security_type")!="COMMON_STOCK" or facts.get("currency")!="USD"
            or facts.get("amount_unit")!=cash.USD_PER_RAW_OLD_SHARE
            or facts.get("quantity_coordinate")!=cash.RAW_OLD_SHARE_COORDINATE
            or facts.get("ordinary_cash_confirmed") is not True or facts.get("noncash_flags_absent") is not True
            or facts.get("special_or_due_bill_indicator") is not False
            or facts.get("late_notice_indicator") is not False
            or entry["identity_binding"]!=payload["identity_binding"]
            or entry["prior_raw_close"]!=payload["prior_raw_close"]
            or entry["original_unsupported_keys"]!=exact or len(exact)!=1
            or facts["exact_frozen_event_key"]!=exact[0]
            or payload.get("source_scope")!="FROZEN_PRE2026_NYSE_COMMON_USD"):
        raise ValueError("CA_POST_VERIFIED_EXACT_SUBJECT_REQUIRED")
    ex=cash._day(exact[0]["effective_date"],"ex_date")
    record=cash._day(facts["record_date"],"corrected_record")
    if (not cash._clock(ex,9,30)<capture<pd.Timestamp("2026-01-01",tz="UTC")
            or early.get("publication_date")!=facts["publication_calendar_date"]
            or early.get("literal_pay_date")!=facts["pay_date"]
            or early.get("literal_record_date")==facts["record_date"]
            or late.get("record_date")!=facts["record_date"]
            or late.get("record_fact_role")!="LATE_ISSUER_HISTORY_CORROBORATED_HISTORICAL_RECORD_FACT; NOT_PRE_EX_SOURCE_AVAILABILITY"):
        raise ValueError("CA_LATE_CORRECTION_CLOCK_MUST_REMAIN_UNKNOWN")
    cells=late["exact_row"]["cells"]
    if (len(cells)!=6 or cells[5]!="Regular Cash"
            or [str(pd.Timestamp(cells[i]).date()) for i in range(4)]!=[
                facts["publication_calendar_date"],str(ex.date()),facts["record_date"],facts["pay_date"]]
            or float(cells[4].lstrip("$"))!=facts["cash_per_raw_share"]):
        raise ValueError("CA_CORRECTED_ISSUER_EXACT_ROW_CONFLICT")
    for ref in payload["source_refs"]:
        target = next((tx["custody_ref"] for tx in source_ref_transport
                       if ref == tx["original_ref"]), ref)
        _pin(target)
    return dict(id="POST_VERIFIED_"+_hash(facts),issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",
        cash_per_common_share=facts["cash_per_raw_share"],cash_is_gross_announced_amount=True,
        currency="USD",currency_basis="EXPLICIT_USD",record_date=facts["record_date"],
        pay_date=facts["pay_date"],publication_date=facts["publication_calendar_date"],
        candidate_ex_date=str(ex.date()),availability_bound=dict(available_at=None),
        ordinary_cash_dividend=True,source_url=late["source_url"],
        source_scope=payload["source_scope"],historical_ex_adjudication_input=facts,
        actual_late_archive_capture_utc=str(capture),
        original_record_literal_preserved=early["literal_record_date"])



LATE_CURRENCY_SOURCE_SCOPE = "FROZEN_PRE2026_LATE_CURRENCY_NYSE_COMMON_USD"
LATE_CURRENCY_ROLE = "SAME_EVENT_LATER_REPORT_USD_ACCOUNTING_FACT"
LATE_CURRENCY_SCOPE = dict(POST_VERIFIED_SCOPE,
    currency_evidence_role=LATE_CURRENCY_ROLE,
    source_scope=LATE_CURRENCY_SOURCE_SCOPE,
    issuer_jurisdiction="BM", security_type="COMMON_STOCK",
    currency_authority="SAME_REPORT_USD_DEFINITION_EXACT_COMMON_CASH_EVENT",
    availability_role="UNKNOWN_NO_PRE_EX_CURRENCY_AUTHORITY")


def _late_currency_terms(payload, entry, *, source_ref_transport=()):
    """Pin same-event late USD facts without changing early terms or clocks."""
    if (payload.get("schema") != "B_FROZEN_HISTORY_LATE_CURRENCY_CASH_SOURCE_PROJECTION_V1"
            or payload.get("clock_role") != "POST_VERIFIED_ACCOUNTING_ONLY"
            or payload.get("currency_evidence_role") != LATE_CURRENCY_ROLE
            or payload.get("source_scope") != LATE_CURRENCY_SOURCE_SCOPE
            or payload.get("historical_available_at") is not None
            or any(payload.get(k) is not False for k in
                   ("strict_PIT", "production_qualified", "quote_qualified", "certified_NAV"))):
        raise ValueError("CA_LATE_CURRENCY_EXACT_RESEARCH_ROLE_REQUIRED")
    facts = copy.deepcopy(payload["source_projection"])
    exact = payload["exact_original_unsupported_keys"]
    if (facts.get("clock_role") != "POST_VERIFIED_ACCOUNTING_ONLY"
            or facts.get("available_at") is not None
            or facts.get("issuer_jurisdiction") != "BM"
            or facts.get("security_type") != "COMMON_STOCK"
            or facts.get("currency") != "USD"
            or facts.get("amount_unit") != cash.USD_PER_RAW_OLD_SHARE
            or facts.get("quantity_coordinate") != cash.RAW_OLD_SHARE_COORDINATE
            or facts.get("ordinary_cash_confirmed") is not True
            or facts.get("noncash_flags_absent") is not True
            or facts.get("special_or_due_bill_indicator") is not False
            or facts.get("late_notice_indicator") is not False
            or entry["identity_binding"] != payload["identity_binding"]
            or entry["prior_raw_close"] != payload["prior_raw_close"]
            or entry["original_unsupported_keys"] != exact or len(exact) != 1
            or facts.get("exact_frozen_event_key") != exact[0]):
        raise ValueError("CA_LATE_CURRENCY_EXACT_SUBJECT_REQUIRED")
    refs = payload["source_refs"]
    def pinned(ref):
        if sum(ref == item for item in refs) != 1:
            raise ValueError("CA_LATE_CURRENCY_NESTED_SOURCE_PIN_REQUIRED")
        target = next((tx["custody_ref"] for tx in source_ref_transport
                       if ref == tx["original_ref"]), ref)
        return _pin(target)
    early_ref = payload["original_cash_source_custody_ref"]
    late_ref = payload["later_same_event_currency_custody_ref"]
    early = json.loads(pinned(early_ref).read_text(encoding="utf-8-sig"))
    late = json.loads(pinned(late_ref).read_text(encoding="utf-8-sig"))
    # Parse only necessary pinned source fragments, not whole issuer reports.
    def fragment(ref):
        from html.parser import HTMLParser
        class Visible(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True); self.parts = []
            def handle_data(self, data): self.parts.append(data)
        parser = Visible(); parser.feed(pinned(ref).read_text(encoding="utf-8-sig"))
        return " ".join(" ".join(parser.parts).split())
    def visible(ref): return pinned(ref).read_text(encoding="utf-8-sig").strip()
    early_text = fragment(early["original_article_body_ref"])
    late_text = fragment(late["necessary_original_cash_paragraph_ref"])
    dollar_text = fragment(late["necessary_original_usd_definition_ref"])
    if (early.get("schema") != "ISSUER_ORDINARY_CASH_SOURCE_CUSTODY_R1"
            or late.get("schema") != "SAME_EVENT_COMMON_CASH_CURRENCY_CORROBORATION_SOURCE_CUSTODY_R1"
            or early_text != visible(early["visible_text_ref"])
            or early_text != early.get("quarterly_cash_clause")
            or late_text != visible(late["cash_visible_text_ref"])
            or late_text != late.get("cash_clause_literal")
            or dollar_text != visible(late["currency_visible_text_ref"])
            or dollar_text != late.get("currency_definition_literal")
            or not re.fullmatch(r"All dollar amounts referred to in this Form 10-[KQ] are in U.S. dollars unless otherwise indicated[.]", dollar_text)
            or late.get("definition_scope") != "THIS_FORM_10_K_OR_Q_ONLY_EXPLICIT"
            or early.get("source_share_unit") != "EXPLICIT_PER_COMMON_SHARE_ON_ITS_COMMON_SHARES"
            or early.get("security_type") != "COMMON_SHARES"
            or any(source.get("issuer") != entry["identity_binding"]["issuer"]
                   or source.get("ticker") != facts["ticker"] for source in (early, late))
            or early.get("listing_identity") != facts["listing_identity"]):
        raise ValueError("CA_LATE_CURRENCY_PINNED_COMMON_CASH_AND_USD_TEXT_REQUIRED")
    amount = facts["cash_per_raw_share"]
    original_amount = re.search(r"dividend (?:of|to) [$]([0-9]+(?:[.][0-9]+)?) per common share", early_text)
    report_amount = re.search(r"quarterly dividends of [$] *([0-9]+[.][0-9]+) per common share", late_text)
    dates = re.findall(r"[A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}", late_text)
    n = len(dates)//2
    pairs = [(str(pd.Timestamp(a).date()), str(pd.Timestamp(b).date()))
             for a,b in zip(dates[:n], dates[n:])]
    match = [item for item in late.get("matches", ())
             if item.get("original_declared_cash_source_custody_ref") == early_ref]
    if (isinstance(amount, bool) or not isinstance(amount, (int,float))
            or not math.isfinite(amount) or amount <= 0
            or original_amount is None or report_amount is None
            or float(original_amount.group(1)) != amount
            or float(report_amount.group(1)) != amount
            or early.get("cash_per_share") != amount
            or early.get("record_date") != facts["record_date"]
            or early.get("pay_date") != facts["pay_date"]
            or early.get("original_key_date") != exact[0]["effective_date"]
            or early.get("original_support_keys") != exact
            or len(dates) != n*2 or n not in (1,2,3,4)
            or pairs.count((facts["record_date"],facts["pay_date"])) != 1
            or len(match) != 1
            or match[0].get("original_support_keys") != exact
            or match[0].get("exact_record_date") != facts["record_date"]
            or match[0].get("exact_pay_date") != facts["pay_date"]
            or float(match[0].get("exact_same_declared_common_share_cash_literal", "nan")) != amount
            or match[0].get("common_share_coordinate_agrees") is not True
            or match[0].get("currency") != "USD"):
        raise ValueError("CA_LATE_CURRENCY_UNIQUE_EXACT_SAME_EVENT_REQUIRED")
    ex = cash._day(exact[0]["effective_date"], "ex_date")
    original_publication = cash._day(early["announcement_date"], "original_cash_publication")
    report_publication = cash._day(late["source_filing_date"], "later_report_publication")
    if (facts.get("publication_calendar_date") != str(original_publication.date())
            or not original_publication < ex < report_publication):
        raise ValueError("CA_LATE_CURRENCY_ORIGINAL_AND_LATE_PUBLICATIONS_REQUIRED")
    def capture(source, publication):
        stamp = pd.Timestamp(source["capture_utc"])
        if pd.isna(stamp) or stamp.tzinfo is None or stamp < publication.tz_localize("UTC"):
            raise ValueError("CA_LATE_CURRENCY_CURRENT_CAPTURE_CLOCK_REQUIRED")
        return str(stamp.tz_convert("UTC"))
    original_capture = capture(early, original_publication)
    late_capture = capture(late, report_publication)
    for ref in refs: pinned(ref)
    binding = dict(currency_evidence_role=LATE_CURRENCY_ROLE,
        status="EXACT_SAME_EVENT_USD_SOURCE_CORROBORATED", available_at=None,
        security_type="COMMON_STOCK", security_id=facts["security_id"],
        ticker=facts["ticker"], listing_identity=facts["listing_identity"], currency="USD",
        cash_per_raw_share=amount, record_date=facts["record_date"], pay_date=facts["pay_date"],
        original_cash_publication_date=str(original_publication.date()),
        later_report_publication_date=str(report_publication.date()),
        original_cash_current_capture_utc=original_capture,
        later_report_current_capture_utc=late_capture,
        original_cash_source_custody_ref=copy.deepcopy(early_ref),
        later_same_event_currency_custody_ref=copy.deepcopy(late_ref),
        report_cash_paragraph_ref=copy.deepcopy(late["necessary_original_cash_paragraph_ref"]),
        same_report_usd_definition_ref=copy.deepcopy(late["necessary_original_usd_definition_ref"]),
        historical_availability_authority="UNKNOWN", not_pre_ex_currency_authority=True)
    facts["late_currency_binding"] = binding
    return dict(id="LATE_CURRENCY_"+_hash(facts), issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"], security_type="COMMON_STOCK",
        cash_per_common_share=amount, cash_is_gross_announced_amount=True,
        currency="USD", currency_basis="EXPLICIT_USD", record_date=facts["record_date"],
        pay_date=facts["pay_date"], publication_date=facts["publication_calendar_date"],
        candidate_ex_date=str(ex.date()), availability_bound=dict(available_at=None),
        ordinary_cash_dividend=True, source_url=early["source_url"],
        source_scope=LATE_CURRENCY_SOURCE_SCOPE, historical_ex_adjudication_input=facts,
        late_currency_binding=binding)


FOREIGN_COMMON_SOURCE_SCOPE = "FROZEN_PRE2026_FOREIGN_NASDAQ_ORDINARY_RAW_SHARE_SAME_FILE_EXPLICIT_USD"
FOREIGN_COMMON_ROLE = "SAME_FILE_EXPLICIT_USD_ORDINARY_SHARE_GROSS_CASH_FROZEN_RESEARCH_COORDINATE"
FOREIGN_COMMON_SCOPE = dict(POST_VERIFIED_SCOPE, source_scope=FOREIGN_COMMON_SOURCE_SCOPE,
    cash_evidence_role=FOREIGN_COMMON_ROLE, issuer_jurisdiction="NON_US_FOREIGN_PRIVATE_ISSUER_SOURCE_LITERAL",
    security_type="COMMON_STOCK", currency_authority="SAME_PROSPECTUS_SUPPLEMENT_EXPLICIT_USD_DEFINITION",
    share_unit_authority="SOURCE_DIRECT_NASDAQ_ORDINARY_SHARE_EXACT_FROZEN_RAW_CLASS_ZERO_QUANTITY_BRIDGE",
    amount_basis="DECLARED_GROSS_BEFORE_SOURCE_REPORTED_TAX_NOT_INVESTOR_NET",
    historical_availability_authority="UNKNOWN", actual_exchange_ex_authority="UNKNOWN")


def _foreign_explicit_usd_common_cash_terms(payload, entry, *, source_ref_transport=()):
    """One same-file ordinary-share USD fact, for retrospective accounting only."""
    flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
    if (payload.get("schema")!="B_FOREIGN_NASDAQ_ORDINARY_SAME_FILE_USD_CASH_SOURCE_PROJECTION_V1"
            or payload.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY"
            or payload.get("source_scope")!=FOREIGN_COMMON_SOURCE_SCOPE
            or payload.get("cash_evidence_role")!=FOREIGN_COMMON_ROLE
            or payload.get("historical_available_at") is not None
            or payload.get("exchange_notice_authority")!="UNKNOWN"
            or payload.get("actual_exchange_ex_authority")!="UNKNOWN"
            or any(payload.get(k) is not False for k in flags)):
        raise ValueError("CA_FOREIGN_COMMON_EXACT_RESEARCH_SCOPE_REQUIRED")
    facts=copy.deepcopy(payload["source_projection"]);exact=payload["exact_original_unsupported_keys"]
    if (entry["identity_binding"]!=payload["identity_binding"] or entry["prior_raw_close"]!=payload["prior_raw_close"]
            or entry["original_unsupported_keys"]!=exact or len(exact)!=1
            or facts.get("exact_frozen_event_key")!=exact[0] or facts.get("frozen_event_exact_row_count")!=1
            or facts.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY" or facts.get("available_at") is not None
            or facts.get("issuer_jurisdiction")!="NON_US_FOREIGN_PRIVATE_ISSUER_SOURCE_LITERAL"
            or facts.get("security_type")!="COMMON_STOCK" or facts.get("currency")!="USD"
            or facts.get("amount_unit")!=cash.USD_PER_RAW_OLD_SHARE or facts.get("quantity_coordinate")!=cash.RAW_OLD_SHARE_COORDINATE
            or facts.get("ordinary_cash_confirmed") is not True or facts.get("noncash_flags_absent") is not True
            or facts.get("special_or_due_bill_indicator") is not False or facts.get("late_notice_indicator") is not False
            or facts.get("ex_date_provenance_role")!="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY"):
        raise ValueError("CA_FOREIGN_COMMON_EXACT_SUBJECT_AND_RAW_UNIT_REQUIRED")
    refs=payload["source_refs"]
    def pinned(ref):
        if sum(ref==r for r in refs)!=1:raise ValueError("CA_FOREIGN_COMMON_NESTED_PIN_REQUIRED")
        return _pin(next((t["custody_ref"] for t in source_ref_transport if t["original_ref"]==ref),ref))
    custody_ref=payload["foreign_same_file_cash_custody_ref"]
    source=json.loads(pinned(custody_ref).read_text(encoding="utf-8-sig"))
    meta_ref=source["confirmed_sec_primary_index_metadata_ref"]
    meta=json.loads(pinned(meta_ref).read_text(encoding="utf-8-sig"))
    if (source.get("schema")!="B_SAME_PROSPECTUS_FOREIGN_NASDAQ_ORDINARY_EXPLICIT_USD_CASH_CUSTODY_V1"
            or source.get("ticker")!=facts["ticker"] or source.get("source_url")!=payload["source_url"]
            or meta.get("schema")!="B_EXACT_PRE2026_SEC_PRIMARY_INDEX_CONFIRMED_SOURCE_METADATA_V1"
            or meta.get("status")!="ACTUAL_PRIMARY_INDEX_CONFIRMED"
            or meta.get("historical_availability_authority")!="UNKNOWN" or meta.get("actual_exchange_ex_authority")!="UNKNOWN"
            or any(meta.get(k) is not False for k in flags)):
        raise ValueError("CA_FOREIGN_COMMON_ACTUAL_SOURCE_AND_INDEX_ROLE_REQUIRED")
    from scripts.storage.refresh_sec_event_originals import FilingText
    def shown(raw):
        parser=FilingText();parser.feed(raw.decode("utf-8"));return " ".join(" ".join(parser.parts).split())
    body_ref=source["original_HTTP_ref"];body_path=pinned(body_ref)
    if ({k:meta["body_ref"][k] for k in ("path","sha256")}!=body_ref
            or body_path.stat().st_size!=meta["body_ref"]["bytes"]):
        raise ValueError("CA_FOREIGN_COMMON_SAME_PHYSICAL_BODY_REQUIRED")
    index_ref={k:meta["index_ref"][k] for k in ("path","sha256")}
    index_raw=pinned(index_ref).read_bytes();index_text=shown(index_raw)
    filed=cash._day(meta["actual_SEC_filed_date"],"actual_SEC_filed_date")
    accession=meta["SEC_accession"];cik=meta["SEC_cik"]
    if (not pd.Timestamp("2023-01-01")<=filed<pd.Timestamp("2026-01-01")
            or type(cik) is not int or cik<=0 or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}",accession)
            or source["source_url"]!=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-','')}/"+source["actual_primary_filename"]
            or not re.search(r"Filing Date\s+"+re.escape(str(filed.date()))+r"\b",index_text)
            or not re.search(r"Accepted\s+"+re.escape(meta["SEC_accepted_literal"])+r"\b",index_text)
            or not re.search(rb'href=["\'][^"\']*'+re.escape(source["actual_primary_filename"].encode())+rb'["\']',index_raw,re.I)):
        raise ValueError("CA_FOREIGN_COMMON_INDEX_FILED_AND_PRIMARY_LINK_REQUIRED")
    texts={}
    for role,item in source["same_file_fragments"].items():
        bounds=item["original_byte_range"]
        if (not isinstance(bounds,list) or len(bounds)!=2 or any(type(v) is not int for v in bounds)
                or not 0<=bounds[0]<bounds[1]<=body_path.stat().st_size or bounds[1]-bounds[0]>65536):
            raise ValueError("CA_FOREIGN_COMMON_BOUNDED_ORIGINAL_RANGE_REQUIRED")
        raw=pinned(item["original_fragment_ref"]).read_bytes()
        with body_path.open("rb") as stream:stream.seek(bounds[0]);original=stream.read(bounds[1]-bounds[0])
        text=shown(raw)
        if (raw!=original or text!=pinned(item["visible_text_ref"]).read_text(encoding="utf-8-sig").strip()
                or text!=item["visible_text"] or _hash(text)!=item["visible_text_content_sha256"]):
            raise ValueError("CA_FOREIGN_COMMON_EXACT_ORIGINAL_FRAGMENT_AND_TEXT_REQUIRED")
        texts[role]=text
    required={"issuer_definition","ordinary_share_title","ordinary_nasdaq_listing","foreign_private_issuer",
              "usd_definition","dividend_policy_title","dividend_cash_terms","ordinary_share_dividend_policy"}
    if set(texts)!=required:raise ValueError("CA_FOREIGN_COMMON_EXACT_SAME_FILE_ROLES_REQUIRED")
    issuer=entry["identity_binding"]["issuer"];ticker=facts["ticker"]
    name=lambda v:re.sub(r"[.,\s]","",v).casefold()
    issuer_match=re.search(r"refer to (.+?), together with its consolidated subsidiaries",texts["issuer_definition"])
    listing=re.fullmatch(r'Our ordinary shares are listed on the Nasdaq(?: Global Select Market)? \(the “Nasdaq”\)(?: and on the [^.]+? \(the “[^”]+”\))?, under the symbol “([^”]+?)(?:[.]”|”[.])',texts["ordinary_nasdaq_listing"])
    # This profile binds the explicitly traded ordinary share. It grants no ADS
    # ratio or share conversion, and does not turn the issuer into a US company.
    if (issuer_match is None or name(issuer_match.group(1))!=name(issuer)
            or texts["ordinary_share_title"]!="Ordinary Shares" or listing is None or listing.group(1)!=ticker
            or facts.get("listing_identity")!="NASDAQ:"+ticker
            or texts["foreign_private_issuer"]!='We are a “foreign private issuer” under applicable U.S. Securities and Exchange Commission (the “SEC”) rules and are eligible for reduced public company disclosure requirements.'
            or not re.fullmatch(r'All references in this prospectus supplement to the terms “[^”]+” and “[^”]+” refer to [^,.]+, and the terms “dollar,” “U.S. dollars” or “[$]” refer to United States dollars[.]',texts["usd_definition"])
            or texts["dividend_policy_title"]!="DIVIDEND POLICY"
            or "The payment of future dividends on our ordinary shares is subject to the discretion of our Board." not in texts["ordinary_share_dividend_policy"]):
        raise ValueError("CA_FOREIGN_COMMON_SAME_ISSUER_DIRECT_ORDINARY_NASDAQ_AND_USD_REQUIRED")
    text=texts["dividend_cash_terms"]
    event_pattern=(r"On ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), our Board declared a dividend of [$]([0-9]+[.][0-9]+) per share[.] "
        r"The dividend’s record date (?:was|is) ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}) and the dividend (?:was|will be) paid on "
        r"([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), after deduction of taxes at the source, at the rate of ([0-9]+[.][0-9]+)%[.]")
    matches=[(str(pd.Timestamp(d).date()),float(a),str(pd.Timestamp(r).date()),str(pd.Timestamp(p).date()),float(t),m.group(0))
        for m in re.finditer(event_pattern,text) for d,a,r,p,t in [m.groups()]]
    selected=source["selected_same_file_event"]
    same=[x for x in matches if x[:4]==(selected["declared_date"],facts["cash_per_raw_share"],facts["record_date"],facts["pay_date"])]
    amount=facts["cash_per_raw_share"]
    if (not text.startswith("We have consistently paid a quarterly dividend to our shareholders.")
            or len(same)!=1 or isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount<=0
            or selected!={"declared_date":same[0][0],"cash_per_ordinary_share":same[0][1],"record_date":same[0][2],"pay_date":same[0][3],"source_withholding_tax_rate_percent":same[0][4],"original_cash_clause_literal":same[0][5]}
            or not pd.Timestamp(same[0][0])<pd.Timestamp(same[0][2])<=pd.Timestamp(same[0][3])
            or facts.get("publication_calendar_date")!=str(filed.date())):
        raise ValueError("CA_FOREIGN_COMMON_ONE_EXACT_GROSS_EVENT_AND_TAX_ROLE_REQUIRED")
    capture=pd.Timestamp(meta["observed_at"])
    if pd.isna(capture) or capture.tzinfo is None or capture<filed.tz_localize("UTC"):
        raise ValueError("CA_FOREIGN_COMMON_AWARE_CURRENT_CAPTURE_REQUIRED")
    class_binding=dict(original_frozen_class_literal="Common Stock",source_common_class_literal="Ordinary Shares",
        role="SOURCE_DIRECT_NASDAQ_ORDINARY_SHARE_EXACT_FROZEN_RAW_CLASS_ZERO_QUANTITY_BRIDGE",
        source_listing_identity="NASDAQ:"+ticker,source_symbol=ticker,source_issuer=issuer,
        source_ordinary_listing_ref=source["same_file_fragments"]["ordinary_nasdaq_listing"]["original_fragment_ref"],
        source_ordinary_class_ref=source["same_file_fragments"]["ordinary_share_title"]["original_fragment_ref"],
        source_ADS_claim=False,share_quantity_effect=False)
    frozen=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=issuer,source_common_class_binding=class_binding)
    if frozen is None:raise ValueError("CA_FOREIGN_COMMON_EXACT_ORIGINAL_FROZEN_RAW_IDENTITY_REQUIRED")
    for ref in refs:pinned(ref)
    binding=dict(cash_evidence_role=FOREIGN_COMMON_ROLE,status="PINNED_SAME_FILE_EXPLICIT_USD_DIRECT_ORDINARY_GROSS_CASH_FACT",
        security_id=facts["security_id"],ticker=ticker,listing_identity="NASDAQ:"+ticker,currency="USD",
        cash_per_raw_share=amount,record_date=facts["record_date"],pay_date=facts["pay_date"],
        actual_SEC_filed_date=str(filed.date()),source_declared_date=same[0][0],
        source_statement_date_role="SOURCE_REPORTED_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY",
        independent_actual_ex_date=None,available_at=None,historical_availability_authority="UNKNOWN",
        exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
        ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
        currency_basis="SAME_PROSPECTUS_SUPPLEMENT_EXPLICIT_USD_DEFINITION",
        share_unit_role=class_binding["role"],source_ADS_claim=False,share_quantity_effect=False,
        source_legal_CUSIP_claim=False,new_legal_identity_authority=False,
        amount_basis="DECLARED_GROSS_BEFORE_SOURCE_REPORTED_TAX_NOT_INVESTOR_NET",
        source_withholding_tax_rate_percent=same[0][4],source_tax_clause=same[0][5],
        investor_net_cash_authority="UNKNOWN_NOT_ESTIMATED",broker_payment_authority="UNKNOWN",
        original_HTTP_ref=body_ref,confirmed_sec_primary_index_metadata_ref=meta_ref,
        same_file_fragments=copy.deepcopy(source["same_file_fragments"]),frozen_account_identity=frozen,**{k:False for k in flags})
    facts["foreign_same_file_explicit_usd_binding"]=binding
    return dict(id="FOREIGN_USD_COMMON_"+_hash(facts),issuer=issuer,listing_identity="NASDAQ:"+ticker,
        security_type="COMMON_STOCK",cash_per_common_share=amount,cash_is_gross_announced_amount=True,
        currency="USD",currency_basis="EXPLICIT_USD",record_date=facts["record_date"],pay_date=facts["pay_date"],
        publication_date=str(filed.date()),candidate_ex_date=exact[0]["effective_date"],availability_bound=dict(available_at=None),
        ordinary_cash_dividend=True,source_url=source["source_url"],source_scope=FOREIGN_COMMON_SOURCE_SCOPE,
        historical_ex_adjudication_input=facts,foreign_same_file_explicit_usd_binding=binding,frozen_account_identity_binding=frozen)


SEC_CASH_SOURCE_SCOPE = "FROZEN_PRE2026_SEC_CASH_FACT_FROZEN_EX_COORDINATE"
SEC_CASH_ROLE = "SEC_SAME_FILE_CASH_FACT_FROZEN_RESEARCH_EX_COORDINATE"
SEC_CASH_SCOPE = dict(POST_VERIFIED_SCOPE,
    cash_evidence_role=SEC_CASH_ROLE, source_scope=SEC_CASH_SOURCE_SCOPE,
    issuer_jurisdiction="US", security_type="COMMON_STOCK",
    availability_role="UNKNOWN_NOT_PRE_EX_PUBLICATION_AUTHORITY",
    ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
    exchange_notice_authority="UNKNOWN", actual_exchange_ex_authority="UNKNOWN")


SEC_PRIMARY_HTML_PROFILE="SEC_PRIMARY_HTML_WITH_EXACT_HISTORICAL_FILING_METADATA"
SEC_PRIMARY_HTML_SCOPE=dict(POST_VERIFIED_SCOPE,source_transport_profile=SEC_PRIMARY_HTML_PROFILE,
    cash_evidence_role=SEC_CASH_ROLE,source_scope=SEC_CASH_SOURCE_SCOPE,
    identity_relation_role="EXACT_SEC_SUBJECT_COMMON_CUSIP_TO_FROZEN_COM_RAW_NAMESPACE_NOT_TICKER_ALIAS",
    source_listing_role="INDEPENDENT_ORIGINAL_LEGAL_COMMON_LISTING_NOT_ACCOUNTING_LABEL",
    availability_role="UNKNOWN_NOT_PRE_EX_PUBLICATION_AUTHORITY",
    actual_exchange_ex_authority="UNKNOWN",exchange_notice_authority="UNKNOWN")

SEC_STATIC_SUBMISSION_PROFILE="SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_EX99_ATTACHMENT"
SEC_STATIC_SUBMISSION_SCOPE=dict(SEC_PRIMARY_HTML_SCOPE,source_transport_profile=SEC_STATIC_SUBMISSION_PROFILE,
    amount_basis="ORIGINAL_PRE_EX_CURRENT_COMMON_SHARE_DECLARATION",publication_role="SAME_SUBMISSION_ACCEPTANCE_NOT_EARLIER_PRESS_DATELINE")


SEC_STATIC_PRIMARY_BODY_PROFILE="SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_PRIMARY_BODY_CASH"
SEC_STATIC_PRIMARY_BODY_SCOPE=dict(SEC_STATIC_SUBMISSION_SCOPE,source_transport_profile=SEC_STATIC_PRIMARY_BODY_PROFILE,
    allowed_primary_forms=["8-K","10-Q","10-K"],cash_document_role="ORIGINAL_PRIMARY_SEC_BODY_CURRENT_COMMON_CASH_DECLARATION")


def _validate_static_sec_submission(source,support,payload,row,facts,*,pinned):
    """One official submission supplies both the parent cover and child cash bytes.

    This only establishes source transport. It never infers share quantities,
    currency from vendor fields, CUSIPs, or a retrospective cash declaration.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from scripts.storage.refresh_sec_event_originals import source_field,canonical_form
    body=pinned(source["original_HTTP_ref"])
    with body.open("rb") as stream:prefix=stream.read(65536)
    header=prefix.split(b"<DOCUMENT>",1)[0]
    primary_body=payload.get("sec_source_transport_profile")==SEC_STATIC_PRIMARY_BODY_PROFILE
    allowed_forms=("8-K","10-Q","10-K") if primary_body else ("8-K",)
    accession=re.search(rb"ACCESSION NUMBER:\s*(\d{10}-\d{2}-\d{6})",header)
    ciks={int(x) for x in re.findall(rb"CENTRAL INDEX KEY:\s*(\d+)",header)}
    filed=re.search(rb"FILED AS OF DATE:\s*(\d{8})",header)
    form=re.search(rb"CONFORMED SUBMISSION TYPE:[ \t]*([^\r\n]+)",header)
    acceptance=source_field(header,"ACCEPTANCE-DATETIME")
    if (accession is None or accession[1].decode()!=row["adsh"] or row["cik"] not in ciks
            or filed is None or filed[1].decode()!=str(row["filed_date"].date()).replace("-","")
            or form is None or canonical_form(form[1].decode())!=row["form"] or row["form"] not in allowed_forms
            or not re.fullmatch(r"\d{14}",acceptance) or acceptance>="20260101000000"):
        raise ValueError("CA_SEC_STATIC_SUBMISSION_PRE2026_HEADER_REQUIRED")
    accepted=datetime.strptime(acceptance,"%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(ZoneInfo("UTC"))
    declared_clock=pd.Timestamp(row["accepted_datetime"])
    if declared_clock.tzinfo is None:declared_clock=declared_clock.tz_localize("America/New_York")
    ex_open=cash._clock(pd.Timestamp(facts["exact_frozen_event_key"]["effective_date"]),9,30)
    if declared_clock.tz_convert("UTC")!=pd.Timestamp(accepted) or pd.Timestamp(accepted)>=ex_open:
        raise ValueError("CA_SEC_STATIC_SUBMISSION_PRE_EX_ORIGINAL_UNIT_REQUIRED")
    binding=source.get("static_submission_binding",{})
    schema="STATIC_SEC_SAME_ACCESSION_PRIMARY_BODY_CASH_TRANSPORT_V1" if primary_body else "STATIC_SEC_SAME_ACCESSION_PARENT_AND_EX99_TRANSPORT_V1"
    published_field="cash_document_published_at_utc" if primary_body else "attachment_published_at_utc"
    if (binding.get("schema")!=schema
            or (primary_body and binding.get("cash_document_role")!="ORIGINAL_PRIMARY_SEC_BODY_CURRENT_COMMON_CASH_DECLARATION")
            or binding.get("accession")!=row["adsh"] or binding.get("issuer_CIK")!=row["cik"]
            or binding.get("original_submission_ref")!=source["original_HTTP_ref"]
            or binding.get("accepted_at_utc")!=pd.Timestamp(accepted).isoformat()
            or binding.get(published_field)!=pd.Timestamp(accepted).isoformat()
            or binding.get("unit_basis")!="ORIGINAL_PRE_EX_CURRENT_COMMON_SHARE_DECLARATION"
            or binding.get("source_publication_not_press_dateline") is not True
            or binding.get("share_quantity_effect") is not False):
        raise ValueError("CA_SEC_STATIC_SUBMISSION_EXACT_TRANSPORT_BINDING_REQUIRED")
    # Read the past-qualified body only after its header clock and identity pass.
    raw=body.read_bytes();documents=[]
    for m in re.finditer(rb"<DOCUMENT>\s*(.*?)</DOCUMENT>",raw,re.S|re.I):
        document=m[1];text=re.search(rb"<TEXT>(.*?)</TEXT>",document,re.S|re.I)
        if text is None:continue
        documents.append(dict(type=source_field(document,"TYPE"),filename=source_field(document,"FILENAME"),
            text_byte_range=[m.start(1)+text.start(1),m.start(1)+text.end(1)]))
    parent=binding.get("parent_document");child=binding.get("cash_attachment_document")
    if (documents.count(parent)!=1 or documents.count(child)!=1 or not documents or parent!=documents[0]
            or canonical_form(parent["type"])!=row["form"] or parent["filename"]!=row["instance"]
            or (parent!=child if primary_body else (re.fullmatch(r"EX-99(?:\.[0-9]+)?",child["type"],re.I) is None or parent==child))):
        raise ValueError("CA_SEC_STATIC_SUBMISSION_PARENT_CHILD_MEMBERSHIP_REQUIRED")
    def within(fragment,document):
        span=fragment.get("original_byte_range",[]);lower,upper=document["text_byte_range"]
        return len(span)==2 and all(type(x) is int for x in span) and lower<=span[0]<span[1]<=upper
    required=("SAME_FILE_REGISTRANT_NAME","SAME_FILE_US_CHARTER","SAME_FILE_COMMON_LISTING_TABLE")
    cover=[x for x in support["fragments"] if x.get("fragment_role") in required]
    selected=payload["selected_original_cash_fragment"]
    if len(cover)!=3 or not all(within(x,parent) for x in cover) or not within(selected,child):
        raise ValueError("CA_SEC_STATIC_SUBMISSION_COVER_CASH_BYTE_BOUNDARY_REQUIRED")
    return dict(schema=binding["schema"],accession=row["adsh"],issuer_CIK=row["cik"],
        original_submission_ref=copy.deepcopy(source["original_HTTP_ref"]),parent_document=copy.deepcopy(parent),
        cash_attachment_document=copy.deepcopy(child),accepted_at_utc=pd.Timestamp(accepted).isoformat(),
        unit_basis=binding["unit_basis"],source_publication_not_press_dateline=True,share_quantity_effect=False,strict_PIT=False,
        **({"cash_document_published_at_utc":pd.Timestamp(accepted).isoformat(),"cash_document_role":binding["cash_document_role"]} if primary_body else {"attachment_published_at_utc":pd.Timestamp(accepted).isoformat()}))


def _static_submission_dated_raw_identity(payload,entry,facts,frozen,*,pinned):
    """Recheck the preselected dated UID/SID using the existing mapping owner."""
    import pyarrow.parquet as pq
    from scripts.research.a2.data.full_selector_account_inputs import identity_links
    bridge=payload.get("static_submission_dated_raw_identity_binding",{})
    role="EXACT_DATED_FROZEN_COM_AND_STATIC_UNIQUE_COMMON_SYMBOL"
    if (bridge.get("schema")!="STATIC_SEC_EXACT_DATED_RAW_COMMON_UID_BRIDGE_V1"
            or bridge.get("role")!=role or bridge.get("ticker")!=facts["ticker"]
            or bridge.get("source_coordinate")!="RAW_ACTUAL_SHARE"
            or bridge.get("new_legal_CUSIP_authority") is not False
            or bridge.get("issuer_CIK_is_security_UID") is not False
            or bridge.get("share_quantity_effect") is not False):
        raise ValueError("CA_SEC_STATIC_EXACT_DATED_RAW_IDENTITY_ROLE_REQUIRED")
    ex=cash._day(facts["exact_frozen_event_key"]["effective_date"],"source_ex")
    if ex>=pd.Timestamp("2026-01-01"):raise ValueError("CA_SEC_STATIC_IDENTITY_PRE2026_REQUIRED")
    calendar_ref=bridge["calendar_ref"];calendar_path=pinned(calendar_ref)
    calendar=pd.DatetimeIndex(pd.to_datetime(pq.read_table(calendar_path,columns=["trade_date"],
        filters=[("trade_date","<",pd.Timestamp("2026-01-01"))]).to_pandas().trade_date))
    if calendar.has_duplicates or not calendar.is_monotonic_increasing or ex not in calendar or calendar.get_loc(ex)==0:
        raise ValueError("CA_SEC_STATIC_IDENTITY_MARKET_CALENDAR_REQUIRED")
    prior=calendar[calendar.get_loc(ex)-1]
    if cash._day(entry["prior_raw_close"]["prior_date"],"prior_identity")!=prior:
        raise ValueError("CA_SEC_STATIC_IDENTITY_PRIOR_CLOCK_CHANGED")
    dated_path=pinned(bridge["dated_identity_ref"])
    dated=pq.read_table(dated_path,columns=["signal_date","ticker","security_id","moomoo_transport_code"],
        filters=[("ticker","==",facts["ticker"]),("signal_date","in",[prior,ex]),
                 ("signal_date","<",pd.Timestamp("2026-01-01"))]).to_pandas()
    if (len(dated)!=2 or dated.duplicated(["signal_date","ticker"]).any()
            or not dated.security_id.astype(str).str.fullmatch(r"[0-9A-Z]{9}").all()):
        raise ValueError("CA_SEC_STATIC_EXACT_PRE_EX_AND_EX_UID_REQUIRED")
    dated["signal_date"]=pd.to_datetime(dated.signal_date)
    keys=dated.rename(columns={"security_id":"cusip"}).copy();keys["security_uid"]="CUSIP:"+keys.cusip.astype(str)
    mapping=json.loads(pinned(bridge["mapping_ref"]).read_text(encoding="utf-8"))
    projection=json.loads(pinned(bridge["identity_projection_ref"]).read_text(encoding="utf-8"))
    links,gaps=identity_links(keys,mapping,projection,dated)
    if (gaps or len(links)!=2 or links.security_uid.nunique()!=1 or links.accounting_sid.nunique()!=1
            or links.security_uid.iloc[0]!="CUSIP:"+frozen["original_source_row"]["cusip"]
            or links.accounting_sid.iloc[0]!=facts["security_id"]):
        raise ValueError("CA_SEC_STATIC_DATED_UID_RAW_ACCOUNTING_SID_MISMATCH")
    return dict(role=role,ticker=facts["ticker"],ex_date=str(ex.date()),prior_date=str(prior.date()),
        security_uid=links.security_uid.iloc[0],accounting_sid=links.accounting_sid.iloc[0],
        source_coordinate="RAW_ACTUAL_SHARE",same_dated_UID_and_SID=True,
        source_refs={key:copy.deepcopy(bridge[key]) for key in ("calendar_ref","dated_identity_ref","mapping_ref","identity_projection_ref")},
        original_frozen_issuer_literal=frozen["original_source_row"].get("issuer_name",entry["identity_binding"]["issuer"]),
        source_legal_name_equivalence_not_claimed=True,new_legal_CUSIP_authority=False,
        issuer_CIK_is_security_UID=False,share_quantity_effect=False)


def _static_submission_cash_statement(text,facts,publication,*,listed_common_class=None):
    """Single literal cash clause in a pre-ex original declaration; no vendor math."""
    from decimal import Decimal
    month=r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    day=month+r"\s+\d{1,2},?\s+20\d{2}"
    amounts=list(re.finditer(r"\bdividend\b[^.;$]{0,140}?\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:cash\s+)?per\s+(?:(?:common|Class\s+[A-C])\s+)?share\b",text,re.I))
    pay=list(re.finditer(r"\bpayable\s+(?:on\s+)?("+day+r")",text,re.I))
    record=list(re.finditer(r"\brecord\s+(?:(?:at|as of)\s+(?:the\s+)?(?:close of (?:business|trading)\s+)?)?(?:on\s+)?("+day+r")",text,re.I))
    explicit_classes={c.upper() for c in re.findall(r"\bClass\s+([A-Z])\b",text,re.I)}
    class_ok=(not explicit_classes if listed_common_class is None else
        listed_common_class in ("A","B","C") and explicit_classes=={listed_common_class})
    if (not class_ok or len(amounts)!=1 or len(pay)!=1 or len(record)!=1 or not re.search(r"\b(?:declared|declaration|approved)\b",text,re.I)
            or re.search(r"\bcash\b",text,re.I) is None
            or re.search(r"\b(?:preferred|depositary|ADS|ADR|adjusted|restated|annualized)\b",text,re.I)):
        raise ValueError("CA_SEC_STATIC_ORIGINAL_SINGLE_COMMON_CASH_CLAUSE_REQUIRED")
    normalized_date=lambda x:str(pd.Timestamp(x).date())
    if (Decimal(amounts[0].group(1))!=Decimal(str(facts["cash_per_raw_share"]))
            or normalized_date(pay[0].group(1))!=facts["pay_date"]
            or normalized_date(record[0].group(1))!=facts["record_date"]
            or pd.Timestamp(publication)>pd.Timestamp(facts["record_date"])):
        raise ValueError("CA_SEC_STATIC_ORIGINAL_CASH_AMOUNT_AND_CLOCK_CHANGED")
    return str(pd.Timestamp(publication).date()),amounts[0].group(1),pay[0].group(1),record[0].group(1)


def _source_subject_cusip_identity(payload,entry,frozen,legal_name,cik,row,*,pinned,fragment):
    """Original subject CUSIP/class source; reporter identity and source clocks stay separate."""
    flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
    name_key=lambda value:re.sub(r"[\s.,]+","",value).casefold()
    identity_ref=payload["source_common_CUSIP_identity_custody_ref"];identity=json.loads(pinned(identity_ref).read_text(encoding="utf-8-sig"))
    common_subject=(identity.get("schema")=="EXACT_PREENTRY_SEC_SUBJECT_ISSUER_COMMON_CUSIP_IDENTITY_CUSTODY_V1"
        and identity.get("source_role")=="OFFICIAL_SEC_SUBJECT_COMPANY_AND_COMMON_TITLE_CUSIP_NOT_REPORTING_OWNER_IDENTITY"
        and identity.get("common_title_literal")=="Common Stock")
    subject_CUSIP_only=(identity.get("schema")=="EXACT_PREENTRY_SEC_SUBJECT_ISSUER_CUSIP_IDENTITY_CUSTODY_V1"
        and identity.get("source_role")=="OFFICIAL_SEC_SUBJECT_COMPANY_CUSIP_WITH_REIT_TITLE_NOT_COMMON_STOCK_LITERAL"
        and identity.get("title_of_class_literal")=="REIT" and identity.get("common_stock_literal_proved") is False
        and identity.get("historical_source_available_at") is None)
    identity_title="Common Stock" if common_subject else "REIT"
    if (not (common_subject or subject_CUSIP_only)
            or identity.get("source_subject_issuer_CIK")!=cik
            or identity.get("raw_CUSIP_literal")!=frozen["original_source_row"]["cusip"]
            or name_key(identity.get("legal_issuer_literal",""))!=name_key(legal_name)
            or any(identity.get(k) not in (None,False) for k in flags)):
        raise ValueError("CA_SEC_HTML_SUBJECT_COMMON_CUSIP_RAW_NAMESPACE_RELATION_REQUIRED")
    identity_body=pinned(identity["original_HTTP_ref"]);header=pinned(identity["original_SEC_header_ref"]).read_bytes()
    with identity_body.open("rb") as stream:prefix=stream.read(min(65536,identity_body.stat().st_size))
    if header.rstrip(b"\r\n") not in prefix:raise ValueError("CA_SEC_HTML_IDENTITY_HEADER_NOT_ORIGINAL_BYTES")
    if header.count(b"SUBJECT COMPANY:")!=1:
        raise ValueError("CA_SEC_HTML_EXACT_ONE_SECURITY_SUBJECT_HEADER_REQUIRED")
    subject=header.decode("utf-8-sig").split("SUBJECT COMPANY:",1)[-1].split("FILED BY:",1)[0]
    if (not re.search(r"CENTRAL INDEX KEY:\s*0*"+str(cik)+r"\b",subject)
            or not re.search(r"COMPANY CONFORMED NAME:\s*"+re.escape(row["name"])+r"\s",subject)):
        raise ValueError("CA_SEC_HTML_REPORTING_OWNER_NOT_SECURITY_SUBJECT")
    identity_item=dict(original_byte_range=identity["source_original_byte_range"],original_fragment_ref=identity["original_fragment_ref"],text_projection_ref=identity["text_projection_ref"],text=identity["identity_fragment_visible_text"],text_typed_content_sha256=identity["visible_text_typed_content_sha256"])
    identity_text=fragment(identity_item,identity_body)
    identity_pub=cash._day(identity["actual_publication_date"],"identity_SEC_filed_date")
    if (identity_pub>cash._day(entry["prior_raw_close"]["prior_date"],"prior_identity_coordinate")
            or re.search(r"FILED AS OF DATE:\s*"+identity_pub.strftime("%Y%m%d")+r"\b",header.decode("utf-8-sig")) is None):
        raise ValueError("CA_SEC_HTML_ORIGINAL_SUBJECT_CUSIP_SOURCE_DATE_CHANGED")
    if (re.search(r"Title of Class of Securities:\s*"+re.escape(identity_title)+r"\s+CUSIP Number:\s*"+re.escape(identity["raw_CUSIP_literal"])+r"\b",identity_text) is None
            or name_key(re.search(r"Name of issuer:\s*(.*?)\s*Title of Class",identity_text).group(1))!=name_key(legal_name)):
        raise ValueError("CA_SEC_HTML_ORIGINAL_SUBJECT_CLASS_CUSIP_CHANGED")
    return identity_ref,identity,identity_title,subject_CUSIP_only


def _sec_primary_html_cash_terms(payload,entry,facts,exact,*,pinned):
    """Primary HTML and actual metadata; source legal symbol and raw label stay distinct."""
    from datetime import datetime
    from decimal import Decimal
    from scripts.storage.refresh_sec_event_originals import FilingText
    from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
    flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
    normalized=lambda value:" ".join(value.split())
    name_key=lambda value:re.sub(r"[\s.,]+","",value).casefold()
    same=lambda a,b:a["sha256"]==b["sha256"] and Path(a["path"]).resolve()==Path(b["path"]).resolve()
    source_ref=payload["sec_cash_source_custody_ref"];source=json.loads(pinned(source_ref).read_text(encoding="utf-8-sig"))
    support_ref=payload["same_file_cash_identity_support_ref"];support=json.loads(pinned(support_ref).read_text(encoding="utf-8-sig"))
    md_ref=payload["historical_sec_filing_metadata_ref"];md=json.loads(pinned(md_ref).read_text(encoding="utf-8-sig"))
    http_ref=source["original_HTTP_ref"];http=pinned(http_ref)
    if (source.get("schema")!="HISTORICAL_SEC_ORIGINAL_CASH_AND_COMMON_COVER_CUSTODY_V1"
            or support.get("schema")!="HISTORICAL_SEC_EXACT_ORIGINAL_CASH_AND_IDENTITY_SIDECAR_V1"
            or not same(support.get("original_HTTP_ref",{}),http_ref)
            or not same(support.get("original_source_custody_ref",{}),source_ref)
            or source.get("ticker")!=facts["ticker"] or support.get("source_url")!=source.get("source_url")
            or any(item.get(k) not in (None,False) for item in (source,support,md) for k in flags)):
        raise ValueError("CA_SEC_HTML_EXACT_PRIMARY_SOURCE_CUSTODIES_REQUIRED")
    columns=["name","cik","adsh","form","filed_date","accepted_datetime","instance"]
    if (md.get("schema")!="EXACT_PRE2026_SEC_FILING_METADATA_ROW_PROJECTION_CUSTODY_V1"
            or md.get("original_metadata_columns")!=columns
            or md.get("original_metadata_row_datetime_encoding_recipe")!="FILED_DATE_AND_ACCEPTED_DATETIME_ISO8601_RECONSTRUCT_DATETIME_FROMISOFORMAT_BEFORE_CONTENT_HASH"
            or md.get("historical_availability_authority")!="UNKNOWN"
            or not same(md["original_metadata_ref"],source["metadata_ref"])):
        raise ValueError("CA_SEC_HTML_EXACT_HISTORICAL_METADATA_REQUIRED")
    row=copy.deepcopy(md["original_metadata_row"])
    if set(row)!=set(columns):raise ValueError("CA_SEC_HTML_METADATA_COLUMNS_CHANGED")
    for field in ("filed_date","accepted_datetime"):row[field]=datetime.fromisoformat(row[field])
    cik=row["cik"];pub=cash._day(row["filed_date"],"SEC_filed_date")
    submission_profile=payload.get("sec_source_transport_profile") in (SEC_STATIC_SUBMISSION_PROFILE,SEC_STATIC_PRIMARY_BODY_PROFILE)
    url=("https://www.sec.gov/Archives/edgar/data/"+str(cik)+"/"+row["adsh"]+".txt" if submission_profile else "https://www.sec.gov/Archives/edgar/data/"+str(cik)+"/"+row["adsh"].replace("-","")+"/"+row["instance"])
    if (type(cik) is not int or cik<=0 or row["form"] not in ("10-K","10-Q","8-K")
            or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}",row["adsh"])
            or not pd.Timestamp("2023-01-01")<=pub<pd.Timestamp("2026-01-01")
            or content_hash(row)!=md["original_metadata_row_content_sha256"]
            or md.get("exact_predicate")!={"cik":cik,"adsh":row["adsh"]}
            or url!=source["source_url"] or url!=md["source_primary_HTML_url"]
            or source.get("issuer_CIK")!=cik or source.get("source_form")!=row["form"]
            or source.get("source_publication_date")!=str(pub.date())
            or facts.get("publication_calendar_date")!=str(pub.date())):
        raise ValueError("CA_SEC_HTML_METADATA_SUBJECT_FILED_DATE_OR_URL_CHANGED")
    import pyarrow.parquet as pq
    metadata_path=pinned(md["original_metadata_ref"])
    with metadata_path.open("rb") as stream:
        parquet=pq.ParquetFile(stream)
        for index in range(parquet.metadata.num_row_groups):
            group=parquet.metadata.row_group(index)
            filed=next(group.column(j) for j in range(group.num_columns) if group.column(j).path_in_schema=="filed_date")
            if filed.statistics is None or pd.Timestamp(filed.statistics.max)>=pd.Timestamp("2026-01-01"):
                raise ValueError("CA_SEC_HTML_PRE2026_METADATA_FOOTER_REQUIRED")
        stream.seek(0);actual=pq.read_table(stream,columns=columns,filters=[("cik","=",cik),("adsh","=",row["adsh"])]).to_pylist()
    if len(actual)!=1 or content_hash(actual[0])!=content_hash(row):
        raise ValueError("CA_SEC_HTML_EXACT_ORIGINAL_METADATA_ROW_CHANGED")
    transport=json.loads(pinned(source["HTTP_transport_ref"]).read_text(encoding="utf-8-sig"))
    if (transport.get("schema")!="HISTORICAL_FIXED_SEC_FREE_CA_SOURCE_TRANSPORT_V1"
            or transport.get("actual_HTTP_status")!=200 or not same(transport["original_HTTP_ref"],http_ref)
            or transport.get("source_url")!=url or not same(transport["source_metadata_ref"],md["original_metadata_ref"])
            or transport.get("actual_metadata_row")!={k:(str(pub.date()) if k=="filed_date" else row[k]) for k in ("name","cik","adsh","filed_date","instance")}
            or any(transport.get(k) is not False for k in flags)):
        raise ValueError("CA_SEC_HTML_ORIGINAL_HTTP_TRANSPORT_CHANGED")
    submission_proof=_validate_static_sec_submission(source,support,payload,row,facts,pinned=pinned) if submission_profile else None
    def fragment(item,body=http):
        span=item["original_byte_range"]
        if (not isinstance(span,list) or len(span)!=2 or any(type(v) is not int for v in span)
                or not 0<=span[0]<span[1]<=body.stat().st_size or span[1]-span[0]>65536):
            raise ValueError("CA_SEC_HTML_BOUNDED_ORIGINAL_FRAGMENT_REQUIRED")
        with body.open("rb") as stream:stream.seek(span[0]);selected=stream.read(span[1]-span[0])
        raw=pinned(item["original_fragment_ref"]).read_bytes()
        parser=FilingText();parser.feed(raw.decode("utf-8"));text=normalized(" ".join(parser.parts))
        literal=item["text"];typed=hashlib.sha256(json.dumps(literal,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        with pinned(item["text_projection_ref"]).open("rb") as stream:saved=stream.read().decode("utf-8-sig")
        if raw!=selected or text!=normalized(literal) or saved not in (literal,literal+"\n") or typed!=item["text_typed_content_sha256"]:
            raise ValueError("CA_SEC_HTML_EXACT_FRAGMENT_AND_TYPED_TEXT_CHANGED")
        return text
    by_role={}
    for item in support["fragments"]:by_role.setdefault(item["fragment_role"],[]).append(item)
    required=("SAME_FILE_REGISTRANT_NAME","SAME_FILE_US_CHARTER","SAME_FILE_COMMON_LISTING_TABLE")
    if any(len(by_role.get(role,[]))!=1 for role in required):
        raise ValueError("CA_SEC_HTML_SAME_FILE_COMMON_IDENTITY_REQUIRED")
    legal_name,US_state,listing=[fragment(by_role[role][0]) for role in required]
    listings=re.findall(r"\b([A-Z][A-Z0-9.\-]*) (?:The )?(New York Stock Exchange|Nasdaq(?: Global Select Market| Global Market| Capital Market| Stock Market)?)\b",listing,re.I if submission_profile else 0)
    if (name_key(legal_name)!=name_key(row["name"]) or not re.fullmatch(_US_CHARTER_STATE_NAMES,US_state,re.I)
            or re.search(r"\bcommon stock\b",listing,re.I) is None or re.search(r"\bpreferred|depositary|ADS\b",listing,re.I)
            or len(listings)!=1 or listings[0][0]!=source["source_original_ticker"]):
        raise ValueError("CA_SEC_HTML_REAL_US_COMMON_LEGAL_LISTING_REQUIRED")
    legal_listing=("NYSE:" if (listings[0][1].casefold()=="new york stock exchange" if submission_profile else listings[0][1]=="New York Stock Exchange") else "NASDAQ:")+listings[0][0]
    if legal_listing.split(":")[0]!=str(facts["listing_identity"]).split(":")[0]:
        raise ValueError("CA_SEC_HTML_SOURCE_AND_RAW_LABEL_VENUE_CLASS_CONFLICT")
    frozen=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry["identity_binding"]["issuer"])
    if frozen is None:raise ValueError("CA_SEC_HTML_EXACT_ORIGINAL_RAW_COM_IDENTITY_REQUIRED")
    profile=payload["sec_cash_statement_profile"]
    if submission_profile != (profile=="STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION"):
        raise ValueError("CA_SEC_STATIC_TRANSPORT_AND_STATEMENT_PROFILE_REQUIRED")
    frozen_common_profile=profile in ("HTML_AUDIT_COMMITTEE_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT","HTML_DECLARATION_RECORD_PAYMENT_COMMON_CASH_TABLE_ROW","STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION")
    if frozen_common_profile:
        original_row=frozen["original_source_row"]
        if (payload.get("source_frozen_common_identity_role")!=FROZEN_COMMON_NAMESPACE_ROLE
                or payload.get("source_common_CUSIP_identity_custody_ref") is not None
                or original_row["ticker"]!=source["source_original_ticker"] or original_row["ticker"]!=facts["ticker"]
                or legal_listing!=facts["listing_identity"]
                or (not submission_profile and name_key(legal_name)!=name_key(entry["identity_binding"]["issuer"]))
                or original_row["title_of_class"]!="COM"):
            raise ValueError("CA_SEC_HTML_EXACT_FROZEN_SAME_SYMBOL_COMMON_NAMESPACE_REQUIRED")
        dated_raw_proof=_static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned) if submission_profile else None
        if submission_profile and frozen["identity"]["security_id"]!=facts["security_id"]:
            # Original generated identity remains provenance; cash belongs to the
            # unchanged RAW accounting SID proven by the existing dated mapper.
            original_core=copy.deepcopy(frozen["identity"])
            raw_core=dict(original_core,security_id=dated_raw_proof["accounting_sid"],
                identity_kind="EXACT_DATED_FROZEN_RAW_ACCOUNTING_SID")
            frozen=dict(frozen,identity=raw_core,identity_payload_sha256=_hash(raw_core),
                original_source_derived_identity=original_core,
                original_source_derived_identity_payload_sha256=_hash(original_core),
                exact_dated_raw_accounting_identity_proof=copy.deepcopy(dated_raw_proof))
        identity_ref=None;identity={"raw_CUSIP_literal":None};identity_title=original_row["title_of_class"];subject_CUSIP_only=False
    else:
        identity_ref,identity,identity_title,subject_CUSIP_only=_source_subject_cusip_identity(payload,entry,frozen,legal_name,cik,row,pinned=pinned,fragment=fragment)
    selected=payload["selected_original_cash_fragment"]
    candidates=source["cash_fragments"]+support["fragments"]
    if sum(selected==item for item in candidates)!=1:raise ValueError("CA_SEC_HTML_EXACT_SELECTED_CASH_FRAGMENT_REQUIRED")
    text=fragment(selected);profile=payload["sec_cash_statement_profile"]
    if profile=="STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION":
        if not submission_profile:raise ValueError("CA_SEC_STATIC_DECLARATION_TRANSPORT_REQUIRED")
        accepted_day=pd.Timestamp(submission_proof["accepted_at_utc"]).tz_convert("America/New_York").normalize().tz_localize(None)
        cover_classes={c.upper() for c in re.findall(r"\bClass\s+([A-Z])\s+Common\s+Stock\b",listing,re.I)}
        all_cover_classes={c.upper() for c in re.findall(r"\bClass\s+([A-Z])\b",listing,re.I)}
        if len(cover_classes)>1 or all_cover_classes!=cover_classes or not cover_classes.issubset({"A","B","C"}):
            raise ValueError("CA_SEC_STATIC_UNKNOWN_OR_MULTIPLE_LISTED_COMMON_CLASSES")
        listed_class=next(iter(cover_classes)) if cover_classes else None
        statement,amount_literal,pay,record=_static_submission_cash_statement(text,facts,accepted_day,listed_common_class=listed_class)
        statement_role="STATIC_SUBMISSION_PUBLIC_ACCEPTANCE_DAY_NOT_BOARD_DATE"
    elif profile=="HTML_EXPLICIT_COMMON_CASH_STATEMENT":
        expression=(r"On ([A-Z][a-z]+ \d{1,2}, \d{4}), we announced that our Board of Directors declared a regular quarterly cash dividend of \$([0-9]+(?:\.[0-9]+)?) per share of common stock that (?:was paid|is payable) on ([A-Z][a-z]+ \d{1,2}, \d{4}), to stockholders of record on ([A-Z][a-z]+ \d{1,2}, \d{4})\.")
        match=re.fullmatch(expression,text)
        if match is None:raise ValueError("CA_SEC_HTML_EXPLICIT_COMMON_CASH_STATEMENT_REQUIRED")
        statement,amount_literal,pay,record=match.groups();statement_role="PUBLIC_ANNOUNCEMENT_DAY_NOT_PRIVATE_BOARD_DATE"
    elif profile=="HTML_AUDIT_COMMITTEE_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT":
        expression=(r"On ([A-Z][a-z]+ \d{1,2}, \d{4}), our Audit Committee declared a quarterly cash dividend to shareholders of \$ *([0-9]+(?:\.[0-9]+)?) per share on the outstanding shares of our common stock\. This quarterly dividend is payable on ([A-Z][a-z]+ \d{1,2}, \d{4}) to the shareholders of record as of ([A-Z][a-z]+ \d{1,2}, \d{4})\.")
        match=re.fullmatch(expression,text)
        if match is None:raise ValueError("CA_SEC_HTML_AUDIT_COMMITTEE_COMMON_CASH_STATEMENT_REQUIRED")
        statement,amount_literal,pay,record=match.groups();statement_role="ORIGINAL_AUDIT_COMMITTEE_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY"
    elif profile=="HTML_DECLARATION_RECORD_DISTRIBUTION_TABLE_ROW":
        header_literal="Declaration Date Record Date Date of Distribution Distribution per Share"
        if selected.get("fragment_role")!="ORIGINAL_DECLARATION_RECORD_DISTRIBUTION_PER_SHARE_TABLE" or not text.startswith(header_literal+" "):
            raise ValueError("CA_SEC_HTML_EXACT_DISTRIBUTION_TABLE_HEADER_REQUIRED")
        expression=r"([A-Z][a-z]+ \d{1,2}, \d{4}) ([A-Z][a-z]+ \d{1,2}, \d{4}) ([A-Z][a-z]+ \d{1,2}, \d{4}) \$ ([0-9]+(?:\.[0-9]+)?)"
        rows=[m for m in re.finditer(expression,text[len(header_literal):]) if m.group(0)==payload["selected_original_cash_statement"]]
        context_ref=payload["same_file_cash_common_table_context_ref"]
        context=json.loads(pinned(context_ref).read_text(encoding="utf-8-sig"))
        if (len(rows)!=1 or context.get("schema")!="SAME_SEC_ORIGINAL_CASH_TABLE_AND_COMMON_UNIT_CONTEXT_SIDECAR_V1"
                or not same(context["original_HTTP_ref"],http_ref)
                or not same(context["original_source_custody_ref"],source_ref)
                or context.get("source_url")!=url or any(context.get(k) not in (None,False) for k in flags)):
            raise ValueError("CA_SEC_HTML_UNIQUE_ROW_AND_SAME_NOTE_CLASS_CONTEXT_REQUIRED")
        roles={}
        for item in context["fragments"]:roles.setdefault(item["fragment_role"],[]).append(item)
        needed=("DISTRIBUTION_POLICY_SECTION_TITLE","SAME_TABLE_EXPLICIT_PAID_IN_CASH_POLICY","SAME_FILE_COMMON_DIVIDEND_UNIT_LABEL")
        if any(len(roles.get(role,[]))!=1 for role in needed):
            raise ValueError("CA_SEC_HTML_TABLE_COMMON_CASH_UNIT_CONTEXT_REQUIRED")
        title,policy,unit=[roles[role][0] for role in needed]
        title_text,policy_text,unit_text=[fragment(item) for item in (title,policy,unit)]
        if (title_text!="Distribution Policy"
                or re.fullmatch(r"The table below is a summary of our distributions declared \(and paid in cash\) during the .+ ended .+:",policy_text) is None
                or unit_text!="Dividends declared per common share"
                or not title["original_byte_range"][1]<=policy["original_byte_range"][0]<policy["original_byte_range"][1]<=selected["original_byte_range"][0]
                or selected["original_byte_range"][0]-policy["original_byte_range"][1]>4096):
            raise ValueError("CA_SEC_HTML_TABLE_COMMON_CASH_UNIT_CONTEXT_REQUIRED")
        statement,record,pay,amount_literal=rows[0].groups();statement_role="ORIGINAL_TABLE_DECLARATION_DATE_NOT_PRIVATE_BOARD_DAY"
    elif profile=="HTML_DECLARATION_RECORD_PAYMENT_COMMON_CASH_TABLE_ROW":
        header_literal="Declaration Date Record Date Payment Date Cash Dividend per Share Total"
        if selected.get("fragment_role")!="ORIGINAL_DECLARATION_RECORD_PAYMENT_CASH_DIVIDEND_PER_SHARE_TABLE" or not text.startswith(header_literal+" "):
            raise ValueError("CA_SEC_HTML_EXACT_COMMON_PAYMENT_TABLE_HEADER_REQUIRED")
        raw=pinned(selected["original_fragment_ref"]).read_bytes();matched=[]
        for raw_row in re.finditer(rb"<tr\b[^>]*>(.*?)</tr>",raw,re.S|re.I):
            parser=FilingText();parser.feed(raw_row.group(1).decode("utf-8"));row_text=normalized(" ".join(parser.parts))
            if row_text==payload["selected_original_cash_statement"]:matched.append((raw_row,row_text))
        if len(matched)!=1:raise ValueError("CA_SEC_HTML_UNIQUE_EXACT_COMMON_PAYMENT_ROW_REQUIRED")
        raw_row,row_text=matched[0]
        match=re.fullmatch(r"([A-Z][a-z]+ \d{1,2}, \d{4}) ([A-Z][a-z]+ \d{1,2}, \d{4}) ([A-Z][a-z]+ \d{1,2}, \d{4}) (?:\$ )?([0-9]+(?:\.[0-9]+)?) (?:\$ )?[0-9]+(?:\.[0-9]+)?",row_text)
        if match is None:raise ValueError("CA_SEC_HTML_COMMON_PAYMENT_ROW_FIELDS_REQUIRED")
        statement,record,pay,amount_literal=match.groups();statement_role="ORIGINAL_TABLE_DECLARATION_DATE_NOT_HISTORICAL_AVAILABILITY"
        context=json.loads(pinned(payload["same_file_cash_common_table_context_ref"]).read_text(encoding="utf-8-sig"))
        if (context.get("schema")!="SAME_SEC_ORIGINAL_CASH_TABLE_AND_COMMON_UNIT_CONTEXT_SIDECAR_V1"
                or not same(context["original_HTTP_ref"],http_ref) or not same(context["original_source_custody_ref"],source_ref)
                or context.get("source_url")!=url or any(context.get(k) is not False for k in flags)):
            raise ValueError("CA_SEC_HTML_COMMON_PAYMENT_SAME_FILE_CONTEXT_REQUIRED")
        roles={}
        for part in context["fragments"]:roles.setdefault(part["fragment_role"],[]).append(part)
        required_roles=("SAME_TABLE_CASH_DIVIDEND_ACTIVITY_INTRODUCTION","SAME_FILE_USD_PER_SHARE_XBRL_UNIT")
        if any(len(roles.get(role,[]))!=1 for role in required_roles):raise ValueError("CA_SEC_HTML_COMMON_PAYMENT_CASH_UNIT_CONTEXT_REQUIRED")
        intro,unit=[roles[role][0] for role in required_roles];intro_text,unit_text=fragment(intro),fragment(unit)
        if (re.fullmatch(r"A summary of (?:the|our) cash dividend activity for the .+ is as follows:",intro_text) is None
                or not intro["original_byte_range"][1]<=selected["original_byte_range"][0]<=intro["original_byte_range"][1]+4096
                or unit_text!="iso4217:USD xbrli:shares"):
            raise ValueError("CA_SEC_HTML_COMMON_PAYMENT_CASH_UNIT_CONTEXT_REQUIRED")
        unit_raw=pinned(unit["original_fragment_ref"]).read_bytes()
        unit_match=re.fullmatch(rb'<xbrli:unit id="([A-Za-z][A-Za-z0-9_]*)"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>',unit_raw)
        if unit_match is None:raise ValueError("CA_SEC_HTML_ORIGINAL_USD_PER_SHARE_UNIT_REQUIRED")
        tags=[]
        for tag in re.finditer(rb"<ix:nonFraction\b[^>]*>.*?</ix:nonFraction>",raw_row.group(1),re.S|re.I):
            attributes=dict((k.decode(),v.decode()) for k,v in re.findall(rb'\b([A-Za-z][A-Za-z0-9]*)="([^"]*)"',tag.group()))
            if attributes.get("name")=="us-gaap:CommonStockDividendsPerShareCashPaid":tags.append((tag,attributes))
        if len(tags)!=1:raise ValueError("CA_SEC_HTML_COMMON_CASH_PER_SHARE_TAG_REQUIRED")
        tag,attributes=tags[0]
        if attributes.get("unitRef")!=unit_match.group(1).decode() or attributes.get("scale")!="0":raise ValueError("CA_SEC_HTML_COMMON_CASH_RAW_PER_SHARE_UNIT_REQUIRED")
        addendum=json.loads(pinned(payload["same_file_per_share_tag_entity_context_addendum_ref"]).read_text(encoding="utf-8-sig"))
        start=selected["original_byte_range"][0]+raw_row.start(1)+tag.start();end=start+len(tag.group())
        entries=[item for item in addendum.get("entries",[]) if item.get("original_HTTP_ref")==http_ref and item.get("source_custody_ref")==source_ref and item.get("selected_original_table_row")==row_text]
        if (addendum.get("schema_version")!="B_SAME_FILE_ORIGINAL_COMMON_DIVIDEND_PER_SHARE_TAG_ENTITY_CONTEXT_CUSTODY_V1"
                or any(addendum.get(k) is not False for k in flags) or len(entries)!=1):
            raise ValueError("CA_SEC_HTML_EXACT_COMMON_TAG_ENTITY_CONTEXT_REQUIRED")
        tag_entry=entries[0];tag_part=tag_entry["per_share_tag_fragment"];entity_part=tag_entry["referenced_context_fragment"]
        tag_text,entity_text=fragment(tag_part),fragment(entity_part)
        entity_raw=pinned(entity_part["original_fragment_ref"]).read_bytes()
        entity=re.fullmatch(rb'<xbrli:context id="([^"]+)">.*?<xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0*([0-9]+)</xbrli:identifier></xbrli:entity>.*?</xbrli:context>',entity_raw,re.S)
        if (tag_part["original_byte_range"]!=[start,end] or pinned(tag_part["original_fragment_ref"]).read_bytes()!=tag.group()
                or tag_entry.get("per_share_tag_original_attributes")!=attributes or entity is None
                or entity.group(1).decode()!=attributes.get("contextRef") or int(entity.group(2))!=cik
                or tag_entry.get("referenced_context_identifier_CIK")!=cik or Decimal(tag_text)!=Decimal(amount_literal)):
            raise ValueError("CA_SEC_HTML_ORIGINAL_COMMON_TAG_VALUE_ENTITY_CHANGED")
    else:raise ValueError("CA_SEC_HTML_EXPLICIT_CASH_STATEMENT_PROFILE_REQUIRED")
    amount=Decimal(amount_literal);statement_day=str(pd.Timestamp(statement).date())
    if (not amount.is_finite() or amount<=0 or amount!=Decimal(str(facts["cash_per_raw_share"]))
            or str(pd.Timestamp(record).date())!=facts["record_date"] or str(pd.Timestamp(pay).date())!=facts["pay_date"]
            or pd.Timestamp(statement)>pub or facts.get("issuer_source_fingerprint")!=selected["original_fragment_ref"]["sha256"]
            or facts.get("identity_source_fingerprint")!=payload["frozen_account_identity_ref"]["sha256"]):
        raise ValueError("CA_SEC_HTML_EXACT_ORIGINAL_COMMON_CASH_TERMS_CHANGED")
    stamp=pd.Timestamp(source["capture_utc"])
    if pd.isna(stamp) or stamp.tzinfo is None or stamp<pub.tz_localize("UTC"):
        raise ValueError("CA_SEC_HTML_CAPTURE_NOT_HISTORICAL_PUBLICATION")
    binding=dict(cash_evidence_role=SEC_CASH_ROLE,source_transport_profile=payload["sec_source_transport_profile"] if submission_profile else SEC_PRIMARY_HTML_PROFILE,
        status="PINNED_SEC_SAME_FILE_CASH_FACT",
        primary_HTML_source_status="PINNED_PRIMARY_HTML_METADATA_AND_FROZEN_RAW_COM_NAMESPACE",
        sec_filer_cik=cik,sec_legal_name_literal=legal_name,source_legal_listing_identity=legal_listing,
        accounting_label_listing_identity=facts["listing_identity"],listing_identity=facts["listing_identity"],security_id=facts["security_id"],ticker=facts["ticker"],
        frozen_account_identity_ref=copy.deepcopy(payload["frozen_account_identity_ref"]),
        source_common_CUSIP_identity_custody_ref=copy.deepcopy(identity_ref),
        source_CUSIP=identity["raw_CUSIP_literal"],source_subject_class_title_literal=identity_title,
        source_subject_CUSIP_role="ORIGINAL_FROZEN_RAW_COM_ONLY_NOT_NEW_LEGAL_CUSIP_AUTHORITY" if frozen_common_profile else ("SAME_SUBJECT_CUSIP_ONLY_COMMON_PROVED_BY_FROZEN_COM_AND_SAME_FILE_CASH_COMMON_LISTING" if subject_CUSIP_only else "SUBJECT_COMMON_STOCK_CUSIP"),
        ticker_alias_inferred=False,new_legal_identity_authority=False,
        actual_SEC_filed_date=str(pub.date()),source_statement_date=statement_day,source_statement_date_role=statement_role,
        private_board_declaration_date=None,selected_original_cash_statement=payload.get("selected_original_cash_statement",text),
        cash_per_raw_share=float(amount),record_date=facts["record_date"],pay_date=facts["pay_date"],
        currency="USD",currency_basis={"NYSE":"INFERRED_USD_US_SEC_FILER_NYSE_COMMON_DOLLAR_CONTEXT","NASDAQ":"INFERRED_USD_US_SEC_FILER_NASDAQ_COMMON_DOLLAR_CONTEXT"}[legal_listing.split(":")[0]],
        ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
        sec_cash_statement_profile=profile,current_capture_utc=str(stamp.tz_convert("UTC")),
        same_file_cover_ref=copy.deepcopy(support_ref),same_file_registrant_name_custody_ref=copy.deepcopy(support_ref),
        ordinary_cash_classification_role="SOURCE_EXPLICIT_REGULAR_QUARTERLY_COMMON_CASH" if profile in ("HTML_EXPLICIT_COMMON_CASH_STATEMENT","HTML_AUDIT_COMMITTEE_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT") else "COMMON_CASH_NORMAL_SCHEDULE_SMALL_CASH_RESEARCH",
        source_regular_quarterly_literal=profile in ("HTML_EXPLICIT_COMMON_CASH_STATEMENT","HTML_AUDIT_COMMITTEE_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT"),
        due_bill_evidence_status="NO_INDICATORS_IN_BOUND_SOURCES_NOT_PROOF_OF_ABSENCE",
        available_at=None,historical_availability_authority="UNKNOWN",exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
        sec_cash_source_custody_ref=copy.deepcopy(source_ref),same_file_cash_identity_support_ref=copy.deepcopy(support_ref),
        historical_sec_filing_metadata_ref=copy.deepcopy(md_ref),original_HTTP_ref=copy.deepcopy(http_ref),
        source_cash_fragment_ref=copy.deepcopy(selected["original_fragment_ref"]),**{k:False for k in flags})
    if frozen_common_profile:
        binding.update(source_legal_CUSIP_claim=False,new_legal_identity_authority=False,
            original_frozen_raw_CUSIP=original_row["cusip"],source_frozen_common_identity_role=FROZEN_COMMON_NAMESPACE_ROLE)
    if submission_profile:
        binding.update(static_submission_transport_proof=submission_proof,static_submission_dated_raw_identity_proof=dated_raw_proof,
            issuer_relation_role="EXACT_DATED_FROZEN_COM_AND_STATIC_UNIQUE_COMMON_SYMBOL",
            original_frozen_issuer_literal=original_row["issuer_name"],source_legal_issuer_literal=legal_name,
            original_and_source_issuer_names_equal=name_key(original_row["issuer_name"])==name_key(legal_name),
            issuer_name_alias_used=False,source_unique_listed_common_class=listed_class,
            source_cash_explicit_common_class=listed_class,
            source_class_match_role="EXPLICIT_SINGLE_LISTED_CLASS_AND_SAME_CASH_CLASS_WITH_EXACT_DATED_RAW_SID" if listed_class else "SOURCE_GENERIC_COMMON_NO_EXPLICIT_CLASS",
            original_frozen_class_literal=original_row["title_of_class"],original_frozen_class_rewritten=False)
    facts["sec_frozen_cash_binding"]=binding
    return dict(id="SEC_FROZEN_CASH_"+_hash(facts),issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",cash_per_common_share=float(amount),
        cash_is_gross_announced_amount=True,currency="USD",currency_basis="INFERRED_USD_CONTEXT",
        record_date=facts["record_date"],pay_date=facts["pay_date"],publication_date=str(pub.date()),
        candidate_ex_date=exact[0]["effective_date"],availability_bound=dict(available_at=None),ordinary_cash_dividend=True,
        source_url=url,source_scope=SEC_CASH_SOURCE_SCOPE,historical_ex_adjudication_input=facts,
        sec_frozen_cash_binding=binding,frozen_account_identity_binding=frozen)



def _sec_frozen_cash_terms(payload, entry, *, source_ref_transport=()):
    """Pinned SEC cash facts; no publication/venue-authority reconstruction."""
    if (payload.get("schema") != "B_FROZEN_HISTORY_SEC_CASH_FACT_SOURCE_PROJECTION_V1"
            or payload.get("clock_role") != "POST_VERIFIED_ACCOUNTING_ONLY"
            or payload.get("cash_evidence_role") != SEC_CASH_ROLE
            or payload.get("source_scope") != SEC_CASH_SOURCE_SCOPE
            or payload.get("historical_available_at") is not None
            or payload.get("exchange_notice_authority") != "UNKNOWN"
            or payload.get("actual_exchange_ex_authority") != "UNKNOWN"
            or any(payload.get(k) is not False for k in
                   ("strict_PIT", "production_qualified", "quote_qualified", "certified_NAV"))):
        raise ValueError("CA_SEC_CASH_EXACT_ACCOUNTING_ROLE_REQUIRED")
    facts = copy.deepcopy(payload["source_projection"])
    exact = payload["exact_original_unsupported_keys"]
    if (facts.get("clock_role") != "POST_VERIFIED_ACCOUNTING_ONLY"
            or facts.get("available_at") is not None
            or facts.get("issuer_jurisdiction") != "US"
            or facts.get("security_type") != "COMMON_STOCK"
            or facts.get("currency") != "USD"
            or facts.get("amount_unit") != cash.USD_PER_RAW_OLD_SHARE
            or facts.get("quantity_coordinate") != cash.RAW_OLD_SHARE_COORDINATE
            or entry["identity_binding"] != payload["identity_binding"]
            or entry["prior_raw_close"] != payload["prior_raw_close"]
            or entry["original_unsupported_keys"] != exact or len(exact) != 1
            or facts.get("exact_frozen_event_key") != exact[0]
            or not (facts.get("ex_date_provenance_role")=="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY"
                or (payload.get("sec_cash_statement_profile")=="SEC_EXPLICIT_CLASS_A_REGULAR_QUARTERLY_COMMON_SHARE_CASH"
                    and facts.get("ex_date_provenance_role")=="NSCC_CNS_PROJECTED_RECORD_T1_FROZEN_RESEARCH_COORDINATE"
                    and isinstance(facts.get("cns_bank_holiday_record_binding"),dict)
                    and facts["cns_bank_holiday_record_binding"].get("policy_id")=="NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH"))):
        raise ValueError("CA_SEC_CASH_EXACT_SUBJECT_REQUIRED")
    refs = payload["source_refs"]
    def pinned(ref):
        if sum(ref == item for item in refs) != 1:
            raise ValueError("CA_SEC_CASH_NESTED_SOURCE_PIN_REQUIRED")
        target = next((tx["custody_ref"] for tx in source_ref_transport
                       if ref == tx["original_ref"]), ref)
        return _pin(target)
    if payload.get("sec_source_transport_profile") in (SEC_PRIMARY_HTML_PROFILE,SEC_STATIC_SUBMISSION_PROFILE,SEC_STATIC_PRIMARY_BODY_PROFILE):
        return _sec_primary_html_cash_terms(payload,entry,facts,exact,pinned=pinned)
    if payload.get("sec_source_transport_profile") is not None:
        raise ValueError("CA_SEC_EXACT_PRIMARY_HTML_TRANSPORT_PROFILE_REQUIRED")
    if payload.get("sec_cash_statement_profile")=="SEC_EXPLICIT_CLASS_A_REGULAR_QUARTERLY_COMMON_SHARE_CASH":
        # Issuer-hosted original HTML plus independent exact SEC filing index.
        # The index is publication-date evidence, never a fabricated submission header.
        from decimal import Decimal
        from scripts.storage.refresh_sec_event_originals import FilingText
        flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
        handoff_ref=payload["class_a_original_handoff_ref"]
        handoff=json.loads(pinned(handoff_ref).read_text(encoding="utf-8-sig"))
        selected=[f for f in handoff.get("cash_candidate_facts",[]) if f.get("original_candidate_unsupported_key")==exact[0]]
        if (handoff.get("schema")!="B_ISSUER_COMMON_CASH_SOURCE_AND_EXISTING_FROZEN_IDENTITY_HANDOFF_V1"
                or any(handoff.get(k) is not False for k in flags) or len(selected)!=1):
            raise ValueError("CA_SEC_CLASS_A_EXACT_ORIGINAL_HANDOFF_REQUIRED")
        fact=selected[0];custody_ref=payload["sec_cash_source_custody_ref"]
        if (fact.get("statement_profile")!=payload["sec_cash_statement_profile"] or fact.get("source_custody_ref")!=custody_ref
                or fact.get("frozen_account_identity_ref")!=payload.get("frozen_account_identity_ref")
                or handoff.get("frozen_account_identity_ref")!=payload.get("frozen_account_identity_ref")
                or fact.get("independent_actual_ex_date") is not None or fact.get("private_board_declaration_date") is not None
                or fact.get("historical_availability_authority")!="UNKNOWN"):
            raise ValueError("CA_SEC_CLASS_A_EXACT_ORIGINAL_FACT_REQUIRED")
        if facts.get("cns_bank_holiday_record_binding") is not None:
            binding_ref=fact.get("cns_bank_holiday_record_binding_ref")
            if (binding_ref is None or json.loads(pinned(binding_ref).read_text(encoding="utf-8-sig"))!=facts["cns_bank_holiday_record_binding"]):
                raise ValueError("CA_SEC_CLASS_A_IMMUTABLE_CNS_HANDOFF_BINDING_REQUIRED")
        source=json.loads(pinned(custody_ref).read_text(encoding="utf-8-sig"));http_ref=source["original_HTTP_ref"];body=pinned(http_ref).read_bytes()
        supplement_ref=fact["same_file_cash_identity_support_ref"]
        supplement=json.loads(pinned(supplement_ref).read_text(encoding="utf-8-sig"))
        metadata_ref=fact["historical_sec_filing_metadata_ref"]
        metadata=json.loads(pinned(metadata_ref).read_text(encoding="utf-8-sig"))
        row=fact["actual_original_SEC_metadata_row"];pub=cash._day(metadata["actual_SEC_filed_date"],"actual_SEC_index_filed_date")
        stamp=pd.Timestamp(source["capture_utc"]);index=pinned(metadata["original_HTTP_ref"]).read_text(encoding="utf-8-sig")
        cik=row.get("cik");url=source.get("source_url","");accession=source.get("accession","")
        if (source.get("schema")!="B_HISTORICAL_SEC_EXACT_CASH_PARAGRAPH_CAPTURE_V1"
                or source.get("source_role")!="ISSUER_HOSTED_HISTORICAL_SEC_8K_ORIGINAL" or source.get("http_status")!=200
                or source.get("historical_availability")!="UNKNOWN" or any(source.get(k) is not False for k in flags)
                or len(body)!=http_ref.get("bytes") or hashlib.sha256(body).hexdigest()!=http_ref["sha256"]
                or supplement.get("schema_version")!="B_HISTORICAL_SAME_FILE_ISSUER_IDENTITY_SUPPLEMENT_V1"
                or supplement.get("original_cash_custody_ref")!=custody_ref or supplement.get("original_http_bytes_ref")!=http_ref
                or supplement.get("source_url")!=url or supplement.get("http_status")!=200
                or supplement.get("received_http_bytes_sha256")!=http_ref["sha256"] or supplement.get("received_bytes")!=len(body)
                or supplement.get("same_exact_original_http_body_sha256") is not True or supplement.get("source_sec_same_file_submission_header_claim") is not False
                or supplement.get("historical_availability_status")!="UNKNOWN" or any(supplement.get(k) is not False for k in flags)
                or supplement.get("source_share_class_literal")!="Class A Common Stock"
                or supplement.get("raw_share_unit_role")!="PER_OUTSTANDING_CLASS_A_COMMON_SHARE_NOT_LLC_UNIT"
                or supplement.get("source_quantity_effect") is not False
                or metadata.get("schema")!="B_SEC_HISTORICAL_EXACT_FILING_METADATA_ORIGINAL_V1" or metadata.get("http_status")!=200
                or metadata.get("exact_pre2026_index_content") is not True or metadata.get("actual_historical_available_at") is not None
                or metadata.get("historical_availability_authority")!="UNKNOWN" or any(metadata.get(k) is not False for k in flags)
                or metadata.get("accession")!=accession or row.get("adsh")!=accession or row.get("file_type")!="8-K"
                or type(cik) is not int or cik<=0 or facts.get("sec_filer_cik")!=cik
                or row.get("file_date")!=str(pub.date()) or row.get("metadata_source_custody_ref")!=metadata_ref
                or row.get("metadata_source_original_ref")!=metadata["original_HTTP_ref"]
                or row.get("metadata_hit_id")!=accession+":"+row.get("file_name","")
                or metadata.get("source_url")!="https://www.sec.gov/Archives/edgar/data/"+str(cik)+"/"+accession.replace("-","")+"/"+accession+"-index.htm"
                or not url.endswith("/"+accession+"/"+row.get("file_name",""))
                or not re.search(r'Filing Date</div>\s*<div class="info">'+re.escape(str(pub.date()))+r'</div>',index)
                or ('/Archives/edgar/data/'+str(cik)+'/'+accession.replace('-','')+'/'+row['file_name']) not in index
                or ('EDGAR Filing Documents for '+accession) not in index
                or pub>=pd.Timestamp("2026-01-01") or pd.isna(stamp) or stamp.tzinfo is None or stamp<pub.tz_localize("UTC")
                or fact.get("actual_SEC_filed_date")!=str(pub.date()) or fact.get("publication_calendar_date")!=str(pub.date())
                or facts.get("publication_calendar_date")!=str(pub.date())):
            raise ValueError("CA_SEC_CLASS_A_EXACT_HTML_INDEX_CUSTODY_REQUIRED")
        def projection(item):
            r=item["fragment_ref"];rng=item["original_byte_range"];raw=pinned(r).read_bytes()
            if (not isinstance(rng,list) or len(rng)!=2 or any(type(n) is not int for n in rng)
                    or not 0<=rng[0]<rng[1]<=len(body) or rng[1]-rng[0]!=len(raw) or len(raw)>16384 or body[rng[0]:rng[1]]!=raw):
                raise ValueError("CA_SEC_CLASS_A_EXACT_ORIGINAL_FRAGMENT_REQUIRED")
            parser=FilingText();parser.feed(raw.decode("utf-8"));text=" ".join(" ".join(parser.parts).split())
            if (text!=item["visible_text"] or hashlib.sha256(text.encode()).hexdigest()!=item["visible_text_utf8_sha256"]
                    or pinned(item["visible_text_ref"]).read_text(encoding="utf-8-sig").strip()!=text):
                raise ValueError("CA_SEC_CLASS_A_ORIGINAL_TEXT_REQUIRED")
            return text,raw
        pieces={}
        for item in supplement.get("identity_fragments",[]):
            if item["role"] in pieces:raise ValueError("CA_SEC_CLASS_A_UNIQUE_IDENTITY_FRAGMENT_REQUIRED")
            pieces[item["role"]]=projection(item)
        if set(pieces)!={"SAME_FILE_REGISTRANT_NAME","SAME_FILE_US_CHARTER","SAME_FILE_COMMON_LISTING_TABLE"}:
            raise ValueError("CA_SEC_CLASS_A_EXACT_SAME_FILE_IDENTITY_REQUIRED")
        name,nameraw=pieces["SAME_FILE_REGISTRANT_NAME"];charter,charterraw=pieces["SAME_FILE_US_CHARTER"];cover,_=pieces["SAME_FILE_COMMON_LISTING_TABLE"]
        issuer_key=lambda v:re.sub(r"[\s.,]+","",v).casefold()
        covermatch=re.fullmatch(r'Title of each class Trading Symbol\(s\) Name of each exchange on which registered Class A Common Stock, \$0[.]001 par value ([A-Z][A-Z0-9.]*) The New York Stock Exchange',cover)
        if (covermatch is None or covermatch.group(1)!=facts["ticker"] or facts["listing_identity"]!="NYSE:"+facts["ticker"]
                or b'dei:EntityRegistrantName' not in nameraw or b'dei:EntityIncorporationStateCountryCode' not in charterraw
                or not re.fullmatch(_US_CHARTER_STATE_NAMES,charter,re.I) or not name
                or issuer_key(name)!=issuer_key(entry["identity_binding"]["issuer"])):
            raise ValueError("CA_SEC_CLASS_A_EXACT_REGISTRANT_LISTED_CLASS_REQUIRED")
        item=fact["selected_original_cash_fragment"];text,_=projection(item)
        if item["original_byte_range"] not in [x["original_byte_range"] for x in source.get("original_cash_paragraphs",[])]:
            raise ValueError("CA_SEC_CLASS_A_EXACT_SELECTED_CASH_PARAGRAPH_REQUIRED")
        pattern=(r'Item 8[.]01 Other Events[.] On (?P<day>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}), the Company[\x27\u2019]s board of directors \(the "Board"\) declared a regular quarterly dividend of \$(?P<amount>[0-9]+[.][0-9]+) per share on the outstanding Class A common stock[.] The regular quarterly dividend will be payable on (?P<pay>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}), to stockholders of record as of the close of business on (?P<record>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})[.]')
        m=re.fullmatch(pattern,text)
        if (m is None or text!=fact["selected_original_cash_statement"] or Decimal(m.group("amount"))!=Decimal(str(facts["cash_per_raw_share"]))
                or Decimal(m.group("amount"))!=Decimal(str(fact["source_cash_amount_per_declared_common_share"]))
                or str(pd.Timestamp(m.group("record")).date())!=facts["record_date"] or facts["record_date"]!=fact["source_record_date"]
                or str(pd.Timestamp(m.group("pay")).date())!=facts["pay_date"] or facts["pay_date"]!=fact["source_payment_date"]
                or str(pd.Timestamp(m.group("day")).date())!=fact["source_company_declaration_date"]
                or not cash._day(fact["source_company_declaration_date"],"source_company_declaration_day")<=pub<=cash._day(facts["record_date"],"record")<=cash._day(facts["pay_date"],"pay",known_future_schedule=True)):
            raise ValueError("CA_SEC_CLASS_A_EXACT_REGULAR_CASH_TERMS_REQUIRED")
        identity_ref=payload["frozen_account_identity_ref"];reuse=json.loads(pinned(identity_ref).read_text(encoding="utf-8-sig"));prior=cash._day(entry["prior_raw_close"]["prior_date"],"prior_class_a_identity")
        rows=[x["original_source_row"] for x in reuse["rows"] if pd.Timestamp(x["original_source_row"]["effective_start"])<=prior<=pd.Timestamp(x["original_source_row"]["effective_end"])]
        if len(rows)!=1:raise ValueError("CA_SEC_CLASS_A_EXACT_ORIGINAL_IDENTITY_INTERVAL_REQUIRED")
        class_binding=dict(status="PINNED_EXACT_FROZEN_CL_A_SOURCE_CLASS_A_COMMON_RAW_UNIT",original_frozen_class_literal="CL A",source_common_class_literal="Class A Common Stock",original_frozen_CUSIP=rows[0]["cusip"],source_common_unit_literal="per share on the outstanding Class A common stock",same_file_identity_supplement_ref=supplement_ref,source_cash_fragment_ref=item["fragment_ref"],original_frozen_class_rewritten=False,no_class_alias=True,share_quantity_effect=False)
        frozen=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry["identity_binding"]["issuer"],source_common_class_binding=class_binding)
        if frozen is None:raise ValueError("CA_SEC_CLASS_A_FROZEN_IDENTITY_REQUIRED")
        binding=dict(cash_evidence_role=SEC_CASH_ROLE,status="PINNED_SEC_INDEX_AND_SAME_FILE_CLASS_A_CASH_FACT",available_at=None,historical_availability_authority="UNKNOWN",exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",ex_coordinate_role=facts["ex_date_provenance_role"],security_id=facts["security_id"],ticker=facts["ticker"],listing_identity=facts["listing_identity"],sec_filer_cik=cik,sec_legal_name_literal=name,currency="USD",currency_basis="INFERRED_USD_US_CHARTER_NYSE_CLASS_A_COMMON_DOLLAR_CONTEXT",cash_per_raw_share=facts["cash_per_raw_share"],record_date=facts["record_date"],pay_date=facts["pay_date"],actual_SEC_filed_date=str(pub.date()),source_company_declaration_date=fact["source_company_declaration_date"],private_board_declaration_date=None,selected_original_cash_statement=text,sec_cash_statement_profile=payload["sec_cash_statement_profile"],selected_statement_typed_content_sha256=_hash(text),current_capture_utc=str(stamp.tz_convert("UTC")),sec_cash_source_custody_ref=custody_ref,same_file_cover_ref=supplement_ref,original_HTTP_ref=http_ref,source_cash_fragment_ref=item["fragment_ref"],historical_SEC_index_metadata_ref=metadata_ref,frozen_account_identity_binding=frozen,source_declared_ex_date=None,independent_actual_ex_date=None)
        exact_ref=lambda r:{k:r[k] for k in ("path","sha256")}
        for name in ("sec_cash_source_custody_ref","same_file_cover_ref","original_HTTP_ref","source_cash_fragment_ref","historical_SEC_index_metadata_ref"):binding[name]=exact_ref(binding[name])
        binding.update(same_file_registrant_name_custody_ref=exact_ref(supplement_ref),source_transport_profile="ISSUER_HOSTED_SEC_8K_HTML_WITH_EXACT_OFFICIAL_INDEX_AND_CLASS_A_COMMON_COVER",source_statement_date=fact["source_company_declaration_date"],source_statement_date_role="SOURCE_REPORTED_COMPANY_BOARD_DECLARATION_DAY_NOT_HISTORICAL_AVAILABILITY",source_original_frozen_class_literal="CL A",source_common_class_literal="Class A Common Stock",source_CUSIP=None,source_legal_CUSIP_claim=False,new_legal_identity_authority=False,share_quantity_effect=False,original_frozen_class_rewritten=False,**{k:False for k in flags})
        for r in refs:pinned(r)
        facts["sec_frozen_cash_binding"]=binding
        return dict(id="SEC_FROZEN_CASH_"+_hash(facts),issuer=entry["identity_binding"]["issuer"],listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",cash_per_common_share=facts["cash_per_raw_share"],cash_is_gross_announced_amount=True,currency="USD",currency_basis="INFERRED_USD_CONTEXT",record_date=facts["record_date"],pay_date=facts["pay_date"],publication_date=str(pub.date()),candidate_ex_date=exact[0]["effective_date"],availability_bound=dict(available_at=None),ordinary_cash_dividend=True,source_url=url,source_scope=SEC_CASH_SOURCE_SCOPE,historical_ex_adjudication_input=facts,sec_frozen_cash_binding=binding,frozen_account_identity_binding=frozen)
    custody_ref = payload["sec_cash_source_custody_ref"]
    source = json.loads(pinned(custody_ref).read_text(encoding="utf-8-sig"))
    cover_ref = source["same_source_identity_projection_ref"]
    cover = json.loads(pinned(cover_ref).read_text(encoding="utf-8-sig"))
    name_ref = payload["same_file_registrant_name_custody_ref"]
    name = json.loads(pinned(name_ref).read_text(encoding="utf-8-sig"))
    http_ref = source["original_HTTP_ref"]
    http = pinned(http_ref)
    def raw_range(start, end):
        if (type(start) is not int or type(end) is not int
                or start < 0 or end <= start or end-start > 65536):
            raise ValueError("CA_SEC_CASH_BOUNDED_ORIGINAL_RANGE_REQUIRED")
        with http.open("rb") as stream:
            stream.seek(start); raw = stream.read(end-start)
        if len(raw) != end-start:
            raise ValueError("CA_SEC_CASH_ORIGINAL_RANGE_INCOMPLETE")
        return raw
    def visible(raw):
        from html.parser import HTMLParser
        class Text(HTMLParser):
            def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]
            def handle_data(self, value): self.parts.append(value)
        parser=Text(); parser.feed(raw.decode("utf-8"))
        return " ".join(" ".join(parser.parts).split())
    def fragment(ref, byte_range):
        with pinned(ref).open("rb") as stream: raw=stream.read()
        if len(raw)>65536 or raw != raw_range(*byte_range):
            raise ValueError("CA_SEC_CASH_FRAGMENT_NOT_EXACT_ORIGINAL_BYTES")
        return visible(raw)
    text = fragment(source["original_cash_fragment_ref"], source["source_original_byte_range"])
    saved = pinned(source["text_projection_ref"]).read_text(encoding="utf-8-sig").strip()
    header = pinned(cover["header_ref"]).read_text(encoding="utf-8-sig")
    pub = cash._day(source["actual_filed_date"], "actual_SEC_filed_date")
    stamp = pd.Timestamp(source["capture_utc"])
    cik = facts.get("sec_filer_cik")
    if (source.get("schema") != "ISSUER_ORIGINAL_ORDINARY_CASH_FRAGMENT_CUSTODY_V1"
            or cover.get("schema") != "HISTORICAL_SEC_ORIGINAL_CASH_COVER_PROJECTION_V1"
            or name.get("schema") != "HISTORICAL_SEC_SAME_FILE_REGISTRANT_NAME_CUSTODY_V1"
            or source.get("ticker") != facts["ticker"]
            or cover.get("original_http_ref") != http_ref or name.get("original_http_ref") != http_ref
            or source.get("source_publication_date_role") != "ACTUAL_SEC_FILED_DATE_NOT_PRIVATE_BOARD_DATE"
            or source.get("announcement_date") != str(pub.date())
            or cover.get("filed_date") != str(pub.date()) or name.get("filed_date") != str(pub.date())
            or type(cik) is not int or cik <= 0
            or any(type(item.get("cik")) is not int or item["cik"] != cik for item in (source,cover,name))
            or source.get("legal_name_literal") != cover.get("legal_name_literal")
            or name.get("SEC_header_name_literal_preserved") != cover.get("legal_name_literal")
            or name.get("same_source_common_listing_projection_ref") != cover_ref
            or any(item.get("historical_availability_authority") != "UNKNOWN" for item in (source,name))
            or any(item.get(k) is not False for item in (source,name) for k in
                   ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
            or entry["identity_binding"].get("sec_filer_cik") != cik
            or entry["identity_binding"].get("sec_legal_name_literal") != cover.get("legal_name_literal")
            or not re.search(r"FILED AS OF DATE:\s*"+pub.strftime("%Y%m%d")+r"\b", header)
            or not re.search(r"CENTRAL INDEX KEY:\s*0*"+str(cik)+r"\b", header)
            or not re.search(r"COMPANY CONFORMED NAME:\s*"+re.escape(cover["legal_name_literal"])+r"\s", header)
            or not re.search(r"STATE OF INCORPORATION:\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b", header)
            or text != saved or text != source.get("dividend_paragraph")
            or source.get("dividend_paragraph_typed_content_sha256") != (hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode("utf-8")).hexdigest() if source.get("dividend_paragraph_typed_content_recipe") == "UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT" else _hash(text))
            or source.get("dividend_paragraph_typed_content_recipe") not in (None,"UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT")
            or pd.isna(stamp) or stamp.tzinfo is None or stamp < pub.tz_localize("UTC")
            or facts.get("publication_calendar_date") != str(pub.date())):
        raise ValueError("CA_SEC_CASH_SAME_FILE_CIK_CLASS_PUBLICATION_REQUIRED")
    profile = payload.get("sec_cash_statement_profile", "EXPLICIT_COMMON_SINGLE_STATEMENT")
    issuer_key=lambda value: re.sub(r"[\s.,]+", "", value).casefold()
    name_text = fragment(name["original_name_fragment_ref"], name["source_original_byte_range"])
    if (name_text != pinned(name["visible_text_ref"]).read_text(encoding="utf-8-sig").strip()
            or name.get("visible_text_typed_content_sha256") != _hash(name_text)
            or name.get("context_literal") not in name_text
            or not re.search(r"Exact name of registrant as specified in its charter", name["context_literal"], re.I)
            or name.get("registrant_name_literal") not in name_text
            or (" ".join(name["registrant_name_literal"].split()).casefold()
                != " ".join(entry["identity_binding"]["issuer"].split()).casefold()
                and " ".join(cover["legal_name_literal"].split()).casefold()
                != " ".join(entry["identity_binding"]["issuer"].split()).casefold()
                and not (profile=="DATED_ISSUER_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT"
                    and issuer_key(name["registrant_name_literal"])==issuer_key(cover["legal_name_literal"])==issuer_key(entry["identity_binding"]["issuer"])))):
        raise ValueError("CA_SEC_CASH_EXACT_SAME_FILE_REGISTRANT_NAME_REQUIRED")
    covers=[]
    for item in cover["cover_fragments"]:
        raw=raw_range(item["raw_byte_start"],item["raw_byte_end"]); shown=visible(raw)
        if hashlib.sha256(raw).hexdigest()!=item["raw_fragment_sha256"] or shown!=item["text"]:
            raise ValueError("CA_SEC_CASH_COVER_NOT_EXACT_ORIGINAL_BYTES")
        venues=[]
        if "New York Stock Exchange" in shown: venues.append("NYSE")
        if re.search(r"\bThe Nasdaq (?:Stock Market LLC|Global Select Market|Global Market|Capital Market)\b",shown): venues.append("NASDAQ")
        if (re.search(r"\bCommon Stock\b",shown,re.I)
                and re.search(r"\b"+re.escape(facts["ticker"])+r"\b",shown)):
            if len(venues)!=1 or re.search(r"\b(?:ADS|ADR|depositary|preferred)\b",shown,re.I):
                raise ValueError("CA_SEC_CASH_AMBIGUOUS_COMMON_VENUE_OR_UNIT")
            covers.append((item,venues[0]+":"+facts["ticker"]))
    if len(covers)!=1 or facts.get("listing_identity")!=covers[0][1]:
        raise ValueError("CA_SEC_CASH_UNIQUE_EXACT_US_COMMON_COVER_REQUIRED")
    profile = payload.get("sec_cash_statement_profile", "EXPLICIT_COMMON_SINGLE_STATEMENT")
    amount=facts["cash_per_raw_share"]
    if isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount<=0:
        raise ValueError("CA_SEC_CASH_POSITIVE_EXACT_AMOUNT_REQUIRED")
    cash_fragment_ref = source["original_cash_fragment_ref"]
    if profile == "EXPLICIT_COMMON_SINGLE_STATEMENT":
        match=re.fullmatch(r"On ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), our Board declared a quarterly cash dividend of [$] *([0-9]+[.][0-9]+) per common share payable on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}),? to holders of record at the close of business on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})[.]",text)
        if match is None or str(pd.Timestamp(match.group(1)).date())!=source.get("private_board_declaration_date"):
            raise ValueError("CA_SEC_CASH_EXPLICIT_COMMON_STATEMENT_REQUIRED")
        declared_amount,record_literal,pay_literal,board_literal = match.group(2),match.group(4),match.group(3),match.group(1)
        selected_text = text
    elif profile == "COMPANY_DECLARED_EXPLICIT_COMMON_CASH_STATEMENT":
        # Current declared amount is anchored before any historical comparison.
        # The original private declaration/announcement day is never filing time.
        statement=(r"(?:Also on|On) ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), "
            r"(?:the Company announced that its board of directors had declared|"
            r"[A-Z][A-Za-z0-9., &-]+ announced that its [Bb]oard of [Dd]irectors had declared|"
            r"the Company[’']s Board of Directors declared|"
            r"the Board of Directors of [A-Z][A-Za-z0-9., &-]+ \(the [“\"]Company[”\"]\) declared|"
            r"the Board of Directors of the Company declared|the Board declared) "
            r"a cash dividend on (?:its|the Company[’']s) common stock of [$]([0-9]+(?:[.][0-9]+)?) per share"
            r"(?:, which is an increase from [$][0-9]+(?:[.][0-9]+)? per share in the prior quarter)?[.] "
            r"(?:The Company has increased the dividend paid per share each year since initiating its dividend in [0-9]{4}[.] )?"
            r"The dividend is payable on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), to stockholders of record as of ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})[.]")
        match=re.fullmatch(statement,text)
        if match is None:
            raise ValueError("CA_SEC_CASH_EXACT_COMPANY_COMMON_STATEMENT_REQUIRED")
        statement_day=str(pd.Timestamp(match.group(1)).date())
        announcement_only="announced that" in text
        statement_role=("PUBLIC_ANNOUNCEMENT_DAY_NOT_PRIVATE_BOARD_DATE" if announcement_only else "SOURCE_EXPLICIT_PRIVATE_BOARD_DECLARATION_DAY")
        if (source.get("source_statement_date")!=statement_day or source.get("source_statement_date_role")!=statement_role
                or source.get("private_board_declaration_date")!=(None if announcement_only else statement_day)):
            raise ValueError("CA_SEC_CASH_ANNOUNCEMENT_AND_PRIVATE_DAY_MUST_REMAIN_DISTINCT")
        issuer_patterns=(r"(?:Also on|On) [A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}, ([A-Z][A-Za-z0-9., &-]+) announced that",r"the Board of Directors of ([A-Z][A-Za-z0-9., &-]+) \(the [“\"]Company[”\"]\) declared")
        labels=[m.group(1) for pattern in issuer_patterns for m in re.finditer(pattern,text)]
        allowed={" ".join(v.split()).casefold() for v in (cover["legal_name_literal"],name["registrant_name_literal"])}
        if any(" ".join(label.split()).casefold() not in allowed for label in labels):
            raise ValueError("CA_SEC_CASH_NAMED_DECLARANT_NOT_SAME_FILE_ISSUER")
        declared_amount,record_literal,pay_literal,board_literal=match.group(2),match.group(4),match.group(3),match.group(1)
        selected_text=text
    elif profile == "DATED_ISSUER_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT":
        # The public release dateline is not a private Board or availability clock.
        statement=(r"(?P<date>[A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}) - [A-Z ]+, [A-Z ]+ - "
            r"(?P<issuer>[A-Z][A-Za-z0-9., &-]+) \((?P<venue>NYSE|NASDAQ): (?P<ticker>[A-Z][A-Z0-9.]*)\) "
            r"\([\"\u201c][^\"\u201d]+[\"\u201d]\) announced today that its Board of Directors has declared "
            r"a quarterly cash dividend of [$](?P<amount>[0-9]+(?:[.][0-9]+)?) per common share[.] "
            r"The quarterly dividend (?:will be|is) payable on (?P<pay>[A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}) "
            r"to common stockholders of record at the close of business on (?P<record>[A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})[.]"
            r"(?: Future dividends are subject to the approval of [A-Z][A-Za-z0-9., &-]+[\u2019']s Board of Directors[.])?")
        match=re.fullmatch(statement,text)
        if (match is None or issuer_key(match.group("issuer"))!=issuer_key(cover["legal_name_literal"])
                or match.group("ticker")!=facts["ticker"]
                or match.group("venue")+":"+match.group("ticker")!=facts["listing_identity"]):
            raise ValueError("CA_SEC_CASH_EXACT_DATED_ISSUER_COMMON_CASH_STATEMENT_REQUIRED")
        statement_day=str(pd.Timestamp(match.group("date")).date())
        statement_role="PUBLIC_ANNOUNCEMENT_DAY_NOT_PRIVATE_BOARD_DATE"
        announcement_only=True
        if (source.get("source_statement_date")!=statement_day or source.get("source_statement_date_role")!=statement_role
                or source.get("private_board_declaration_date") is not None):
            raise ValueError("CA_SEC_CASH_ANNOUNCEMENT_AND_PRIVATE_DAY_MUST_REMAIN_DISTINCT")
        declared_amount,record_literal,pay_literal,board_literal=match.group("amount"),match.group("record"),match.group("pay"),match.group("date")
        selected_text=text
    elif profile == "SAME_FILE_COMMON_POLICY_MULTI_STATEMENT":
        # The exact selected statement stays inside the original multi-quarter
        # paragraph. Its private Board date is never a publication clock.
        cash_fragment_ref = source["original_two_statement_paragraph_ref"]
        paragraph = fragment(cash_fragment_ref,source["original_two_statement_byte_range"])
        policy = source["same_source_common_cash_policy_ref"]
        policy_text = fragment(policy["fragment_ref"],policy["original_byte_range"])
        if (policy_text != pinned(policy["text_projection_ref"]).read_text(encoding="utf-8-sig").strip()
                or _hash(policy_text) != policy["paragraph_typed_content_sha256"]
                or not re.search(r"The Board of Directors determines whether to declare cash dividends on our common stock and the timing and amount",policy_text)):
            raise ValueError("CA_SEC_CASH_SAME_FILE_COMMON_DIVIDEND_POLICY_REQUIRED")
        expression=r"On ([0-9]{1,2} [A-Z][a-z]+ [0-9]{4}), the Board of Directors declared a quarterly dividend of [$] *([0-9]+[.][0-9]+) per share that (?:was|is) payable on ([0-9]{1,2} [A-Z][a-z]+ [0-9]{4}) to shareholders of record at the close of business on ([0-9]{1,2} [A-Z][a-z]+ [0-9]{4})[.]"
        statements=[m for m in re.finditer(expression,paragraph) if m.group(0)==payload.get("selected_original_cash_statement")]
        if len(statements)!=1:
            raise ValueError("CA_SEC_CASH_EXACT_UNIQUE_SELECTED_ORIGINAL_STATEMENT_REQUIRED")
        match=statements[0]
        declared_amount,record_literal,pay_literal,board_literal = match.group(2),match.group(4),match.group(3),match.group(1)
        selected_text = match.group(0)
    else:
        raise ValueError("CA_SEC_CASH_STATEMENT_PROFILE_UNKNOWN")
    board = (None if profile in ("COMPANY_DECLARED_EXPLICIT_COMMON_CASH_STATEMENT", "DATED_ISSUER_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT") and announcement_only else cash._day(str(pd.Timestamp(board_literal).date()),"selected_private_board_date"))
    source_statement_day=cash._day(str(pd.Timestamp(board_literal).date()),"selected_source_statement_date")
    if (float(declared_amount)!=amount or str(pd.Timestamp(pay_literal).date())!=facts["pay_date"]
            or str(pd.Timestamp(record_literal).date())!=facts["record_date"] or source_statement_day>pub):
        raise ValueError("CA_SEC_CASH_EXACT_DECLARED_COMMON_TERMS_REQUIRED")
    for ref in refs: pinned(ref)
    binding=dict(cash_evidence_role=SEC_CASH_ROLE,status="PINNED_SEC_SAME_FILE_CASH_FACT",
        available_at=None,historical_availability_authority="UNKNOWN",
        exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
        ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
        sec_filer_cik=cik,sec_legal_name_literal=cover["legal_name_literal"],
        security_id=facts["security_id"],ticker=facts["ticker"],listing_identity=facts["listing_identity"],
        currency="USD",currency_basis=("INFERRED_USD_US_SEC_FILER_NYSE_COMMON_DOLLAR_CONTEXT" if covers[0][1].startswith("NYSE:") else "INFERRED_USD_US_SEC_FILER_NASDAQ_COMMON_DOLLAR_CONTEXT"),
        cash_per_raw_share=amount,record_date=facts["record_date"],pay_date=facts["pay_date"],
        actual_SEC_filed_date=str(pub.date()),private_board_declaration_date=None if board is None else str(board.date()),
        selected_original_cash_statement=selected_text,sec_cash_statement_profile=profile,
        selected_statement_typed_content_sha256=_hash(selected_text),
        current_capture_utc=str(stamp.tz_convert("UTC")),sec_cash_source_custody_ref=copy.deepcopy(custody_ref),
        same_file_cover_ref=copy.deepcopy(cover_ref),same_file_registrant_name_custody_ref=copy.deepcopy(name_ref),
        original_HTTP_ref=copy.deepcopy(http_ref),source_cash_fragment_ref=copy.deepcopy(cash_fragment_ref))
    if profile in ("COMPANY_DECLARED_EXPLICIT_COMMON_CASH_STATEMENT", "DATED_ISSUER_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT"):
        binding.update(source_statement_date=str(source_statement_day.date()),source_statement_date_role=statement_role)
    if profile=="DATED_ISSUER_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT":
        binding["frozen_account_identity_binding"]=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry["identity_binding"]["issuer"])
        if binding["frozen_account_identity_binding"] is None:
            raise ValueError("CA_SEC_DATED_ISSUER_FROZEN_RAW_COMMON_IDENTITY_REQUIRED")
    facts["sec_frozen_cash_binding"]=binding
    return dict(id="SEC_FROZEN_CASH_"+_hash(facts),issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",
        cash_per_common_share=amount,cash_is_gross_announced_amount=True,currency="USD",
        currency_basis="INFERRED_USD_CONTEXT",record_date=facts["record_date"],pay_date=facts["pay_date"],
        publication_date=str(pub.date()),candidate_ex_date=exact[0]["effective_date"],
        availability_bound=dict(available_at=None),ordinary_cash_dividend=True,source_url=source["source_url"],
        source_scope=SEC_CASH_SOURCE_SCOPE,historical_ex_adjudication_input=facts,
        sec_frozen_cash_binding=binding,
        **(dict(frozen_account_identity_binding=copy.deepcopy(binding["frozen_account_identity_binding"]))
           if profile=="DATED_ISSUER_EXPLICIT_QUARTERLY_COMMON_CASH_STATEMENT" else {}))


REPORT_CASH_SOURCE_SCOPE = "FROZEN_PRE2026_REPORT_CASH_TABLE_FROZEN_EX_COORDINATE"
REPORT_CASH_ROLE = "REPORT_SAME_FILE_COMMON_CASH_TABLE_FROZEN_RESEARCH_EX_COORDINATE"
REPORT_CASH_SCOPE = dict(POST_VERIFIED_SCOPE,
    cash_evidence_role=REPORT_CASH_ROLE, source_scope=REPORT_CASH_SOURCE_SCOPE,
    issuer_jurisdiction="US", security_type="COMMON_STOCK",
    currency_authority="SAME_REPORT_US_CHARTER_NYSE_COMMON_DOLLAR_CONTEXT",
    availability_role="UNKNOWN_NOT_PRE_EX_PUBLICATION_AUTHORITY",
    ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
    exchange_notice_authority="UNKNOWN", actual_exchange_ex_authority="UNKNOWN")


REPORT_NYSE_PRE_T1_NONBUSINESS_SCOPE = dict(
    policy_id=cash.NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH,
    cash_source_scope=REPORT_CASH_SOURCE_SCOPE,
    record_before_exclusive="2024-05-28",
    calendar_role="SOURCE_BOUND_LEGAL_SESSION_CALENDAR",
    rule_role="NYSE_RULE235_CURRENT_PRE_T1_NONBUSINESS_RECORD",
    exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",strict_PIT=False)


DATED_COMMON_UNIT_SOURCE_SCOPE = "FROZEN_PRE2026_DATED_NOTICE_COMMON_UNIT_BRIDGE"
DATED_COMMON_UNIT_ROLE = "DATED_NOTICE_SAME_ISSUER_FROZEN_COMMON_UNIT_RESEARCH_BRIDGE"
DATED_COMMON_UNIT_SCOPE = dict(POST_VERIFIED_SCOPE,
    cash_evidence_role=DATED_COMMON_UNIT_ROLE,source_scope=DATED_COMMON_UNIT_SOURCE_SCOPE,
    issuer_jurisdiction="US",security_type="COMMON_STOCK",
    unit_source_role="ORIGINAL_FROZEN_COM_RAW_SHARE_AND_REPORT_COMMON_POLICY_AND_DATED_NOTICE",
    availability_role="UNKNOWN_NOT_PRE_EX_IDENTITY_OR_REPORT_PUBLICATION_AUTHORITY",
    ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
    exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN")


def _report_common_class_context(payload,entry,facts,*,pinned,raw_text,text_hash,normalized):
    """The existing two-page report source gate, reused for class/unit facts."""
    custody_ref=payload["report_cash_source_custody_ref"]
    source=json.loads(pinned(custody_ref).read_text(encoding="utf-8-sig"))
    transport_ref=source["source_transport_ref"]
    transport=json.loads(pinned(transport_ref).read_text(encoding="utf-8-sig"))
    original_ref=source["original_report_ref"]
    captured_descriptor=source.get("schema")=="HUM_ORIGINAL_REPORT_SAME_FILE_COMMON_CASH_CUSTODY_V1"
    if captured_descriptor:
        # The actual streamed source has a different descriptor and current
        # capture clock. Do not relabel it as an R18 HTTP-end receipt.
        profile_ok=(source.get("source_role")=="THIRD_PARTY_PUBLIC_MIRROR_OF_ORIGINAL_ISSUER_REPORT"
            and source.get("pdf_extract_text_layout_mode") is False
            and source.get("extractor_api")=="pypdf.PdfReader.pages[zero_based].extract_text()"
            and source.get("page_saved_bytes_recipe")=="UTF8_EXACT_PYPDF_TEXT_PLUS_ONE_TERMINAL_LF"
            and source.get("projection_normalization_recipe")=="NONE_RAW_PYPDF_TEXT_PRESERVED_KERNING_SPLITS_DECLARED"
            and source.get("source_publication_authority")=="UNKNOWN_NOT_REPORT_METADATA_CREATION_MIRROR_MTIME_OR_URL_YEAR"
            and transport.get("schema")=="HISTORICAL_SOURCE_HTTP_TRANSPORT_V1"
            and transport.get("status_code")==200 and transport.get("capture_complete") is True
            and transport.get("actual_captured_body_sha256")==original_ref["sha256"]
            and type(transport.get("actual_captured_byte_count")) is int
            and transport["actual_captured_byte_count"]>0
            and transport.get("scope")=="EXACT"+str(cash._day(source["source_report_fiscal_year_ended"],"report_period").year)+"_ORIGINAL_REPORT_COVER_AND_ITEM5_CASH_ONLY"
            and transport.get("url")==source["source_url"]
            and transport.get("original_publication_date") is None
            and transport.get("source_role")=="THIRD_PARTY_PUBLIC_MIRROR_OF_ORIGINAL_ISSUER_REPORT_NOT_ISSUER_HTTP")
        stamp_value=transport.get("current_capture_utc")
    else:
        profile_ok=(source.get("schema")=="HISTORICAL_ORIGINAL_ISSUER_REPORT_SAME_FILE_COMMON_CASH_CUSTODY_V1"
            and source.get("source_role")=="THIRD_PARTY_MIRROR_OF_ORIGINAL_ISSUER_REPORT_SAME_FILE_COMMON_CASH"
            and source.get("pdf_extract_text_layout_mode")=="plain_default"
            and source.get("extractor_api")=="PdfReader.pages[page_zero_based].extract_text()"
            and transport.get("schema")=="HISTORICAL_MIRROR_ISSUER_REPORT_ORIGINAL_PDF_TRANSPORT_V1"
            and transport.get("actual_status")==200
            and transport.get("original_HTTP_sha256")==original_ref["sha256"]
            and transport.get("source_url")==source["source_url"]
            and transport.get("source_publication_date") is None
            and transport.get("source_role")=="THIRD_PARTY_PUBLIC_MIRROR_OF_ISSUER_REPORT_NOT_ISSUER_HOSTED_HTTP"
            and all(transport.get(k) is False for k in ("strict_PIT","production_qualified","quote_qualified")))
        stamp_value=transport.get("request_end_utc")
    if (not profile_ok or source.get("ticker")!=facts["ticker"]
            or source.get("source_publication_date") is not None or source.get("cash_available_at") is not None
            or source.get("source_direct_ex_date") is not None
            or source.get("historical_availability_authority")!="UNKNOWN"
            or any(source.get(k) is not False for k in
                   ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
            or transport.get("original_HTTP_ref")!=original_ref
            or not source["source_url"].startswith("https://")
            or transport.get("historical_availability_authority")!="UNKNOWN"):
        raise ValueError("CA_REPORT_CASH_UNKNOWN_CLOCK_AND_HONEST_TRANSPORT_REQUIRED")
    stamp=pd.Timestamp(stamp_value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("CA_REPORT_CASH_AWARE_CURRENT_CUSTODY_REQUIRED")
    # Reuse the installed PDF extractor. Only the two declared source pages are
    # extracted; report metadata dates and other report pages are not consumed.
    from scripts.storage.refresh_sec_event_originals import load_pdf_package
    reader_type, extractor=load_pdf_package(source["pdf_extractor"]["path"])
    if extractor != source["pdf_extractor"]:
        raise ValueError("CA_REPORT_CASH_PINNED_EXTRACTOR_REQUIRED")
    indexes=(source["page_zero_based"],source["cover_page_zero_based"])
    if any(type(i) is not int or i<0 for i in indexes):
        raise ValueError("CA_REPORT_CASH_BOUNDED_PAGE_COORDINATES_REQUIRED")
    with pinned(original_ref).open("rb") as stream:
        if hashlib.file_digest(stream,"sha256").hexdigest()!=original_ref["sha256"]:
            raise ValueError("CA_REPORT_CASH_ORIGINAL_PDF_CHANGED")
        if captured_descriptor and stream.tell()!=transport["actual_captured_byte_count"]:
            raise ValueError("CA_REPORT_CASH_CAPTURED_BODY_BYTE_COUNT_CHANGED")
        stream.seek(0); reader=reader_type(stream)
        if any(i>=len(reader.pages) for i in indexes):
            raise ValueError("CA_REPORT_CASH_BOUNDED_PAGE_COORDINATES_REQUIRED")
        page_text=reader.pages[indexes[0]].extract_text()
        cover_text=reader.pages[indexes[1]].extract_text()
    saved=raw_text(source["page_text_ref"])
    cover_literal=source["cover_identity_literal"]
    cover_saved=pinned(source["cover_identity_fragment_ref"]).read_text(encoding="utf-8-sig")
    if (saved not in (page_text,page_text+"\n") or text_hash(page_text)!=source["original_page_text_typed_content_sha256"]
            or normalized(cover_saved)!=normalized(cover_literal)
            or text_hash(cover_literal)!=source["cover_identity_literal_typed_content_sha256"]
            or normalized(cover_text).count(normalized(cover_literal))!=1):
        raise ValueError("CA_REPORT_CASH_ORIGINAL_PAGE_PROJECTION_CHANGED")
    full_cover_ref=payload["complete_cover_page_ref"]
    full_cover=raw_text(full_cover_ref)
    if full_cover not in (cover_text,cover_text+"\n"):
        raise ValueError("CA_REPORT_CASH_ORIGINAL_COVER_PAGE_CHANGED")
    text=normalized(page_text); cover=normalized(cover_literal)
    # Whitespace-only semantic keys tolerate PDF glyph spacing. Original
    # extraction, saved bytes, literals and typed commitments remain above.
    semantic=lambda value: re.sub(r"\s+","",value)
    text_key=semantic(text);cover_key=semantic(cover)
    issuer=source["source_issuer_literal"]
    issuer_key=lambda s: re.sub(r"[\s.,]+","",s).casefold()
    fiscal=cash._day(source["source_report_fiscal_year_ended"],"report_period")
    if (fiscal>=pd.Timestamp("2026-01-01") or
            normalized(cover).count(issuer+" (Exact name of registrant as specified in its charter)")!=1
            or issuer_key(issuer)!=issuer_key(entry["identity_binding"]["issuer"])
            or not re.search(r"For the fiscal year ended\s+"+re.escape(fiscal.strftime("%B"))+
                r"\s+0?"+str(fiscal.day)+r",\s+"+str(fiscal.year)+r"\b",cover)):
        raise ValueError("CA_REPORT_CASH_SAME_REPORT_ISSUER_AND_PERIOD_REQUIRED")
    # The existing USD-context meaning is retained: a real US charter, NYSE
    # common class and dollar cash amount, rather than any report dollar sign.
    states=_US_CHARTER_STATE_NAMES
    if (not re.search(r"\b(?:"+states+r")\s+\(State or other jurisdiction of incorporation (?:or|of) organization\)",cover)
            or source.get("source_currency_literal")!="$"
            or semantic(source["source_common_class_literal"]) not in cover_key
            or not re.fullmatch(r"Commonstock,.*",semantic(source["source_common_class_literal"]),re.I)
            or source.get("source_symbol_literal")!=facts["ticker"]
            or semantic(source["source_listing_literal"])!="NewYorkStockExchange"
            or facts["listing_identity"]!="NYSE:"+facts["ticker"]
            or "TradingSymbol"+facts["ticker"]+"NameofexchangeonwhichregisteredNewYorkStockExchange" not in cover_key):
        raise ValueError("CA_REPORT_CASH_US_COMMON_DOLLAR_CONTEXT_REQUIRED")
    listing=source["same_report_common_listing_literal"]
    context=source["cash_table_context_literal"]; headers=source["cash_table_headers_literal"]
    listing_key=semantic(listing);context_key=semantic(context);headers_key=semantic(headers)
    expected_listing="Our common stock trades on the New York Stock Exchange under the symbol "+facts["ticker"]+"."
    if (listing_key!=semantic(expected_listing)
            or text_key.count(listing_key)!=1 or text_key.count(context_key)!=1 or text_key.count(headers_key)!=1
            or not re.search(r"\bITEM 5\s*\.",text)
            or not re.search(r"REGISTRANT[’']S COMMON EQUITY",text)
            or "quarterlycashdividendpolicy" not in context_key.lower()
            or "dividendpayments" not in context_key.lower()
            or ("dividendequivalentrights" in context_key.lower() and
                "excludingdividendequivalentrights" not in context_key.lower())
            or not headers_key.startswith("RecordDatePaymentDateAmountperShare")
            or not text_key.index(listing_key)<text_key.index(context_key)<text_key.index(headers_key)):
        raise ValueError("CA_REPORT_CASH_COMMON_CHAPTER_TABLE_CONTEXT_REQUIRED")
    whitespace_semantics_used=(source["source_common_class_literal"] not in cover
        or source["source_listing_literal"]!="New York Stock Exchange" or listing!=expected_listing
        or text.count(context)!=1 or text.count(headers)!=1)
    return dict(reader_type=reader_type,transport=transport,
        custody_ref=custody_ref,
        source=source,
        transport_ref=transport_ref,
        original_ref=original_ref,
        stamp=stamp,
        extractor=extractor,
        page_text=page_text,
        full_cover_ref=full_cover_ref,
        text_key=text_key,
        semantic=semantic,
        headers_key=headers_key,
        context_key=context_key,
        issuer=issuer,
        issuer_key=issuer_key,
        fiscal=fiscal,
        whitespace_semantics_used=whitespace_semantics_used,
        captured_descriptor=captured_descriptor)


def _existing_frozen_common_identity(payload,entry,facts,*,pinned,issuer,source_common_class_binding=None):
    """Reuse exact original raw COM rows; no publication or legal UID grant."""
    issuer_key=lambda s: re.sub(r"[\s.,]+","",s).casefold()
    frozen_identity=None; identity_ref=payload.get("frozen_account_identity_ref")
    if identity_ref is not None:
        if entry.get("frozen_account_identity_ref")!=identity_ref:
            raise ValueError("CA_REPORT_CASH_FROZEN_IDENTITY_REF_CHANGED")
        reuse=json.loads(pinned(identity_ref).read_text(encoding="utf-8-sig"))
        if (reuse.get("schema_version")!="B_EXISTING_FROZEN_RAW_COMMON_IDENTITY_REUSE_V1"
                or reuse.get("status")!="EXACT_ORIGINAL_FROZEN_IDENTITY_ROWS_REUSED_NOT_NEW_SECURITY_MASTER"
                or reuse.get("ticker")!=facts["ticker"] or reuse.get("available_at") is not None
                or reuse.get("historical_publication_authority")!="UNKNOWN"
                or reuse.get("interval_semantics")!="ORIGINAL_FROZEN_RESEARCH_EFFECTIVE_INTERVAL_NOT_PUBLICATION_TIMESTAMP"
                or reuse.get("original_date_type")!="pandas.Timestamp"
                or reuse.get("encoded_date_representation")!="YYYY-MM-DD_RECONSTRUCT_PANDAS_TIMESTAMP_BEFORE_ORIGINAL_TYPED_HASH"
                or any(reuse.get(k) is not False for k in ("interval_extension","new_security_master","ticker_alias",
                    "share_quantity_effect","strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                or type(reuse.get("row_count")) is not int or reuse["row_count"]!=len(reuse["rows"])):
            raise ValueError("CA_REPORT_CASH_ORIGINAL_FROZEN_IDENTITY_ROLE_REQUIRED")
        interval_ref=reuse["original_uid_intervals_ref"]
        manifest=json.loads(pinned(reuse["original_frozen_input_manifest_ref"]).read_text(encoding="utf-8-sig"))
        if {k:manifest["sources"]["uid_intervals"][k] for k in ("path","sha256")}!=interval_ref:
            raise ValueError("CA_REPORT_CASH_ORIGINAL_FROZEN_INTERVAL_PIN_REQUIRED")
        pinned(reuse["content_hash_owner_ref"]);pinned(reuse["original_held_guard_owner_ref"])
        from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
        columns=["ticker","effective_start","effective_end","security_id","security_id_type","cusip",
            "issuer_name","title_of_class","moomoo_transport_code","mapping_status","mapping_source","source_filing"]
        if reuse["source_identity_columns"]!=columns:
            raise ValueError("CA_REPORT_CASH_ORIGINAL_IDENTITY_COLUMNS_CHANGED")
        rows=[]
        for item in reuse["rows"]:
            row=copy.deepcopy(item["original_source_row"])
            if set(row)!=set(columns):raise ValueError("CA_REPORT_CASH_ORIGINAL_IDENTITY_ROW_CHANGED")
            for key in ("effective_start","effective_end"):row[key]=pd.Timestamp(row[key])
            if (content_hash(row)!=item["original_source_row_content_sha256"]
                    or not row["effective_start"]<=row["effective_end"]<pd.Timestamp("2026-01-01")):
                raise ValueError("CA_REPORT_CASH_ORIGINAL_IDENTITY_ROW_CHANGED")
            rows.append(row)
        prior=cash._day(entry["prior_raw_close"]["prior_date"],"prior_identity_coordinate")
        matches=[row for row in rows if row["effective_start"]<=prior<=row["effective_end"]]
        if len(matches)!=1:raise ValueError("CA_REPORT_CASH_UNIQUE_FROZEN_IDENTITY_INTERVAL_REQUIRED")
        row=matches[0]
        if (row["ticker"]!=facts["ticker"] or row["moomoo_transport_code"]!="US."+facts["ticker"]
                or row["security_id_type"]!="CUSIP" or row["security_id"]!=row["cusip"]
                or not re.fullmatch(r"[0-9A-Z]{9}",row["cusip"])
                or not (row["title_of_class"]=="COM" or (isinstance(source_common_class_binding,dict)
                    and row["title_of_class"]==source_common_class_binding.get("original_frozen_class_literal")=="COM SHS"
                    and source_common_class_binding.get("source_common_class_literal")=="Common Stock") or (isinstance(source_common_class_binding,dict)
                    and row["title_of_class"]==source_common_class_binding.get("original_frozen_class_literal")=="Common Stock"
                    and source_common_class_binding.get("source_common_class_literal")=="Ordinary Shares"
                    and source_common_class_binding.get("role")=="SOURCE_DIRECT_NASDAQ_ORDINARY_SHARE_EXACT_FROZEN_RAW_CLASS_ZERO_QUANTITY_BRIDGE"
                    and source_common_class_binding.get("source_listing_identity")==facts["listing_identity"]=="NASDAQ:"+facts["ticker"]
                    and source_common_class_binding.get("source_symbol")==facts["ticker"] and issuer_key(source_common_class_binding.get("source_issuer",""))==issuer_key(issuer)
                    and source_common_class_binding.get("source_ADS_claim") is False and source_common_class_binding.get("share_quantity_effect") is False
                    and all(isinstance(source_common_class_binding.get(k),dict) and source_common_class_binding[k] in payload["source_refs"] for k in ("source_ordinary_listing_ref","source_ordinary_class_ref"))) or (isinstance(source_common_class_binding,dict)
                    and source_common_class_binding.get("status")=="PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT"
                    and source_common_class_binding.get("source_CUSIP")==row["cusip"]
                    and source_common_class_binding.get("original_frozen_class_literal")==row["title_of_class"]
                    and source_common_class_binding.get("source_common_class_literal")=="Common Stock"
                    and source_common_class_binding.get("no_class_alias") is True
                    and source_common_class_binding.get("original_frozen_class_rewritten") is False) or (isinstance(source_common_class_binding,dict)
                    and source_common_class_binding.get("status")=="PINNED_EXACT_FROZEN_CL_A_SOURCE_CLASS_A_COMMON_RAW_UNIT"
                    and row["title_of_class"]==source_common_class_binding.get("original_frozen_class_literal")=="CL A"
                    and source_common_class_binding.get("source_common_class_literal")=="Class A Common Stock"
                    and source_common_class_binding.get("original_frozen_CUSIP")==row["cusip"]
                    and source_common_class_binding.get("source_common_unit_literal")=="per share on the outstanding Class A common stock"
                    and source_common_class_binding.get("original_frozen_class_rewritten") is False
                    and source_common_class_binding.get("no_class_alias") is True
                    and source_common_class_binding.get("share_quantity_effect") is False
                    and all(isinstance(source_common_class_binding.get(k),dict) and source_common_class_binding[k] in payload["source_refs"] for k in ("same_file_identity_supplement_ref","source_cash_fragment_ref"))))
                or row["mapping_status"]!="RESOLVED" or not isinstance(row["source_filing"],str) or not row["source_filing"].strip()
                or issuer_key(row["issuer_name"])!=issuer_key(issuer)):
            raise ValueError("CA_REPORT_CASH_FROZEN_RAW_COMMON_IDENTITY_MISMATCH")
        # Only the original issuer identity columns are read, after pre2026
        # row-group date bounds. No price, model, membership or UID is rewritten.
        import pyarrow.parquet as pq
        with pinned(interval_ref).open("rb") as stream:
            stream.seek(0,2);source_bytes=stream.tell();stream.seek(0)
            if (type(manifest["sources"]["uid_intervals"].get("bytes")) is not int
                    or manifest["sources"]["uid_intervals"]["bytes"]!=source_bytes):
                raise ValueError("CA_REPORT_CASH_ORIGINAL_INTERVAL_BYTE_COUNT_CHANGED")
            parquet=pq.ParquetFile(stream)
            for i in range(parquet.metadata.num_row_groups):
                group=parquet.metadata.row_group(i)
                for key in ("effective_start","effective_end"):
                    col=next(group.column(j) for j in range(group.num_columns) if group.column(j).path_in_schema==key)
                    if col.statistics is None or pd.Timestamp(col.statistics.max)>=pd.Timestamp("2026-01-01"):
                        raise ValueError("CA_REPORT_CASH_PRE2026_ORIGINAL_IDENTITY_METADATA_REQUIRED")
            stream.seek(0)
            frame=pq.read_table(stream,columns=columns,filters=[("ticker","=",facts["ticker"]),
                ("effective_start","<=",prior.to_pydatetime()),("effective_end",">=",prior.to_pydatetime())]).to_pandas()
        if len(frame)!=1 or content_hash(frame.iloc[0].to_dict())!=content_hash(row):
            raise ValueError("CA_REPORT_CASH_EXACT_ORIGINAL_IDENTITY_ROW_REQUIRED")
        ib=entry["identity_binding"];core={k:ib[k] for k in
            ("security_id","identity_kind","issuer","ticker","listing_identity","security_type")}
        if (core["identity_kind"]!="SOURCE_DERIVED_ISSUER_COMMON_CLASS" or core["security_type"]!="COMMON_STOCK"
                or core["security_id"]!=cash.source_derived_security_id(core["issuer"],core["ticker"],core["listing_identity"])
                or (core["security_id"]!=facts["security_id"]
                    and payload.get("sec_source_transport_profile") not in (SEC_STATIC_SUBMISSION_PROFILE,SEC_STATIC_PRIMARY_BODY_PROFILE))
                or core["ticker"]!=facts["ticker"]
                or core["listing_identity"]!=facts["listing_identity"] or issuer_key(core["issuer"])!=issuer_key(row["issuer_name"])
                or ib.get("identity_payload_sha256")!=_hash(core) or ib.get("available_at") is not None
                or ib.get("source_reference")!=identity_ref["path"] or ib.get("source_fingerprint")!=identity_ref["sha256"]):
            raise ValueError("CA_REPORT_CASH_EXACT_FROZEN_ACCOUNTING_LABEL_REQUIRED")
        frozen_identity=dict(identity=core,identity_payload_sha256=_hash(core),
            source_reference=identity_ref["path"],source_fingerprint=identity_ref["sha256"],available_at=None,
            CUSIP_claim=False,historical_availability_qualified=False,legal_identity_authority_granted=False,
            identity_clock_role="ORIGINAL_FROZEN_EFFECTIVE_INTERVAL_NOT_PUBLICATION",
            original_frozen_identity_ref=identity_ref,original_uid_intervals_ref=interval_ref,
            original_source_row_content_sha256=content_hash(row),
            original_source_row=next(copy.deepcopy(item["original_source_row"]) for item in reuse["rows"]
                if item["original_source_row_content_sha256"]==content_hash(row)),
            original_date_type="pandas.Timestamp",encoded_date_representation=reuse["encoded_date_representation"])
    elif entry.get("frozen_account_identity_ref") is not None:
        raise ValueError("CA_REPORT_CASH_FROZEN_IDENTITY_REF_CHANGED")
    if frozen_identity is not None and source_common_class_binding is not None:
        frozen_identity["exact_source_common_class_binding"]=copy.deepcopy(source_common_class_binding)
    return frozen_identity


def _report_frozen_cash_terms(payload, entry, *, source_ref_transport=(),
                              nyse_nonbusiness_scope=None,calendar=None,calendar_binding=None):
    """Same-report common cash facts; source clocks remain explicitly unknown."""
    if (payload.get("schema") != "B_FROZEN_HISTORY_REPORT_CASH_TABLE_SOURCE_PROJECTION_V1"
            or payload.get("clock_role") != "POST_VERIFIED_ACCOUNTING_ONLY"
            or payload.get("cash_evidence_role") != REPORT_CASH_ROLE
            or payload.get("source_scope") != REPORT_CASH_SOURCE_SCOPE
            or payload.get("historical_available_at") is not None
            or payload.get("exchange_notice_authority") != "UNKNOWN"
            or payload.get("actual_exchange_ex_authority") != "UNKNOWN"
            or any(payload.get(k) is not False for k in
                   ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
        raise ValueError("CA_REPORT_CASH_EXACT_ACCOUNTING_ROLE_REQUIRED")
    facts = copy.deepcopy(payload["source_projection"]); exact = payload["exact_original_unsupported_keys"]
    if (facts.get("clock_role") != "POST_VERIFIED_ACCOUNTING_ONLY"
            or facts.get("available_at") is not None or facts.get("publication_calendar_date") is not None
            or facts.get("issuer_jurisdiction") != "US" or facts.get("security_type") != "COMMON_STOCK"
            or facts.get("currency") != "USD" or facts.get("amount_unit") != cash.USD_PER_RAW_OLD_SHARE
            or facts.get("quantity_coordinate") != cash.RAW_OLD_SHARE_COORDINATE
            or entry["identity_binding"] != payload["identity_binding"]
            or entry["prior_raw_close"] != payload["prior_raw_close"]
            or entry["original_unsupported_keys"] != exact or len(exact) != 1
            or facts.get("exact_frozen_event_key") != exact[0]
            or facts.get("ex_date_provenance_role") !=
               "EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY"):
        raise ValueError("CA_REPORT_CASH_EXACT_SUBJECT_REQUIRED")
    refs=payload["source_refs"]
    def pinned(ref):
        if sum(ref == r for r in refs) != 1:
            raise ValueError("CA_REPORT_CASH_NESTED_SOURCE_PIN_REQUIRED")
        target=next((tx["custody_ref"] for tx in source_ref_transport if ref==tx["original_ref"]),ref)
        return _pin(target)
    def raw_text(ref):
        with pinned(ref).open("rb") as stream:
            return stream.read().decode("utf-8-sig")
    def text_hash(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
            ensure_ascii=False,default=str).encode()).hexdigest()
    def normalized(value): return " ".join(value.split())
    common=_report_common_class_context(payload,entry,facts,pinned=pinned,raw_text=raw_text,
        text_hash=text_hash,normalized=normalized)
    reader_type=common["reader_type"]
    transport=common["transport"]
    custody_ref=common["custody_ref"]
    source=common["source"]
    transport_ref=common["transport_ref"]
    original_ref=common["original_ref"]
    stamp=common["stamp"]
    extractor=common["extractor"]
    page_text=common["page_text"]
    full_cover_ref=common["full_cover_ref"]
    text_key=common["text_key"]
    semantic=common["semantic"]
    headers_key=common["headers_key"]
    context_key=common["context_key"]
    issuer=common["issuer"]
    issuer_key=common["issuer_key"]
    fiscal=common["fiscal"]
    whitespace_semantics_used=common["whitespace_semantics_used"]
    captured_descriptor=common["captured_descriptor"]
    subject={k:exact[0][k] for k in ("ticker","effective_date","reason","source_fingerprint")}
    selected=[r for r in source["cash_sources"] if all(r["original_key"].get(k)==v for k,v in subject.items())]
    if len(selected)!=1:
        raise ValueError("CA_REPORT_CASH_UNIQUE_ORIGINAL_SUBJECT_REQUIRED")
    selected=selected[0]; literal=selected["selected_cash_literal"]
    literal_key=semantic(literal)
    if (text_key.count(literal_key)!=1 or text_key.index(literal_key)<text_key.index(headers_key)
            or text_hash(literal)!=selected["selected_cash_literal_typed_content_sha256"]
            or selected.get("source_publication_date") is not None
            or selected.get("cash_available_at") is not None or selected.get("private_board_day") is not None):
        raise ValueError("CA_REPORT_CASH_UNIQUE_ORIGINAL_CASH_LITERAL_REQUIRED")
    context_span=text_key[text_key.index(context_key):text_key.index(literal_key)+len(literal_key)]
    if any(token in context_span.casefold() for token in ("ads","adr","preferred","special","liquidat","merger")):
        raise ValueError("CA_REPORT_CASH_COMMON_ORDINARY_CONTEXT_REQUIRED")
    profile=selected["selected_cash_profile"]; interval=None
    if profile=="TABLE_ROW":
        table_start=text_key.index(headers_key)+len(headers_key)
        after_table=re.search(r"In[A-Za-z]+\d{4},theBoarddeclared",text_key[table_start:])
        table_end=table_start+after_table.start() if after_table else len(text_key)
        if text_key[table_start:table_end].count(literal_key)!=1:
            raise ValueError("CA_REPORT_CASH_ROW_NOT_IN_ORIGINAL_TABLE")
        m=re.fullmatch(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}/\d{1,2}/\d{4})\s+\$\s*([0-9]+(?:\.[0-9]+)?)",normalized(literal))
        if m is None:
            raise ValueError("CA_REPORT_CASH_COMMON_ORDINARY_TABLE_ROW_REQUIRED")
        record_literal,pay_literal,amount_literal=m.groups()
    elif profile=="MONTH_DECLARATION_STATEMENT":
        m=re.fullmatch(r"In([A-Za-z]+)(\d{4}),theBoarddeclaredacashdividendof\$([0-9]+(?:\.[0-9]+)?)persharepayableon([A-Za-z]+)(\d{1,2}),(\d{4})tostockholdersofrecordon([A-Za-z]+)(\d{1,2}),(\d{4})\.?",literal_key)
        if m is None:
            raise ValueError("CA_REPORT_CASH_EXPLICIT_MONTH_STATEMENT_REQUIRED")
        month_name,year,amount_literal,pay_month,pay_day,pay_year,record_month,record_day,record_year=m.groups()
        month=month_name+" "+year;pay_literal=pay_month+" "+pay_day+", "+pay_year;record_literal=record_month+" "+record_day+", "+record_year
        whitespace_semantics_used=whitespace_semantics_used or literal!=normalized(literal) or "cash dividend" not in literal
        start=pd.Timestamp(month); end=start+pd.offsets.MonthBegin(1)
        interval=dict(start_inclusive=str(start.date()),end_exclusive=str(end.date()),
            source_literal=month,precision="MONTH_ONLY_NOT_A_DAY_OR_PUBLICATION")
        if captured_descriptor:
            declared_interval=dict(start=str(start.date()),end=str((end-pd.Timedelta(days=1)).date()),
                role="SOURCE_DECLARATION_MONTH_ONLY_NOT_PUBLICATION_OR_EXACT_BOARD_DAY")
            month_matches=selected.get("declaration_month_interval")==declared_interval
        else:
            month_matches=(semantic(month)==semantic(selected.get("source_declaration_month_literal",""))
                and selected.get("source_declaration_month_interval")==[str(start.date()),str((end-pd.Timedelta(days=1)).date())])
        if not month_matches or end>cash._day(exact[0]["effective_date"],"ex_date"):
            raise ValueError("CA_REPORT_CASH_DECLARATION_MONTH_MUST_BE_WHOLE_PRE_EX")
    else:
        raise ValueError("CA_REPORT_CASH_STATEMENT_PROFILE_UNKNOWN")
    amount=facts["cash_per_raw_share"]
    if (isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount<=0
            or float(amount_literal)!=amount or float(selected["source_cash_amount_literal"])!=amount
            or str(cash._day(str(pd.Timestamp(record_literal).date()),"selected_record").date())!=facts["record_date"]
            or str(cash._day(str(pd.Timestamp(pay_literal).date()),"selected_pay").date())!=facts["pay_date"]
            or selected["source_record_date"]!=facts["record_date"] or selected["source_pay_date"]!=facts["pay_date"]):
        raise ValueError("CA_REPORT_CASH_EXACT_AMOUNT_RECORD_PAY_REQUIRED")

    frozen_identity=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=issuer)
    for ref in refs: pinned(ref)
    binding=dict(status="PINNED_REPORT_SAME_FILE_COMMON_CASH_FACT",cash_evidence_role=REPORT_CASH_ROLE,
        available_at=None,publication_calendar_date=None,private_board_declaration_date=None,
        historical_availability_authority="UNKNOWN",exchange_notice_authority="UNKNOWN",
        actual_exchange_ex_authority="UNKNOWN",ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
        currency_basis="INFERRED_USD_US_REPORT_NYSE_COMMON_DOLLAR_CONTEXT",
        security_id=facts["security_id"],ticker=facts["ticker"],listing_identity=facts["listing_identity"],
        issuer=entry["identity_binding"]["issuer"],currency="USD",cash_per_raw_share=amount,
        record_date=facts["record_date"],pay_date=facts["pay_date"],report_period_end=str(fiscal.date()),
        declaration_month_interval=interval,selected_cash_profile=profile,selected_cash_literal=literal,
        original_page_text_typed_content_sha256=text_hash(page_text),current_capture_utc=str(stamp),
        report_cash_source_custody_ref=custody_ref,original_report_ref=original_ref,source_transport_ref=transport_ref,
        source_cash_page_ref=source["page_text_ref"],same_file_cover_fragment_ref=source["cover_identity_fragment_ref"],
        original_pdf_extractor=extractor,transport_role=source["source_role"],
        complete_cover_page_ref=full_cover_ref)
    if captured_descriptor:
        binding.update(source_descriptor_profile="ACTUAL_MIRROR_CAPTURED_REPORT_DESCRIPTOR_V1",
            current_capture_clock_role="ACTUAL_CURRENT_CAPTURE_UTC_NOT_HTTP_END_OR_PUBLICATION",
            source_transport_flags_role="ORIGINAL_TRANSPORT_UNDECLARED_NOT_INVENTED_SOURCE_FLAGS",
            strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False,
            actual_captured_body_sha256=transport["actual_captured_body_sha256"],
            actual_captured_byte_count=transport["actual_captured_byte_count"])
    if whitespace_semantics_used:
        binding["whitespace_semantic_role"]="WHITESPACE_ONLY_DERIVED_KEYS_RAW_LITERALS_AND_PAGE_HASH_UNCHANGED"
    rule_ref=payload.get("report_nyse_pre_t1_nonbusiness_rule_ref")
    if rule_ref is not None:
        if (not isinstance(nyse_nonbusiness_scope,dict) or rule_ref!=nyse_nonbusiness_scope["rule_source_ref"]
                or calendar is None or not isinstance(calendar_binding,dict)):
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_EXPLICIT_SCOPE_REQUIRED")
        rule_source=json.loads(raw_text(rule_ref))
        if (rule_source.get("schema")!="OFFICIAL_PRE2026_NYSE_RULE235_NECESSARY_PAGE_SOURCE_FACTS_V1"
                or rule_source.get("source_document_year")!=2024
                or rule_source.get("scope")!="NYSE_RULE235_CURRENT_PRE_TPLUS1_PROSE_AND_GOOD_FRIDAY_HOLIDAY_CLAUSE"
                or rule_source.get("strict_PIT") is not False or rule_source.get("algorithm_changed") is not False
                or rule_source.get("exchange_notice_authority")!="UNKNOWN"
                or rule_source.get("actual_exchange_ex_authority")!="UNKNOWN" or rule_source["extractor"]!=extractor):
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_ORIGINAL_RULE_ROLE_REQUIRED")
        rule_original=rule_source["original_ref"];rule_transport_ref=rule_source["transport_ref"]
        rule_transport=json.loads(raw_text(rule_transport_ref))
        if (rule_transport.get("actual_status")!=200
                or rule_transport.get("request_url")!="https://www.nyse.com/publicdocs/nyse/markets/nyse/rule-filings/filings/2024/SR-NYSE-2024-19.pdf"
                or rule_transport.get("source_role")!="NYSE_OFFICIAL_PRE2026_RULE_FILING"
                or rule_transport.get("original_HTTP_ref")!=rule_original or rule_transport.get("strict_PIT") is not False):
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_OFFICIAL_TRANSPORT_REQUIRED")
        rule_path=pinned(rule_original)
        pages=rule_source["selected_pages"]
        if not isinstance(pages,list) or [p.get("page_zero_based") for p in pages]!=[3,23]:
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_EXACT_RULE_PAGES_REQUIRED")
        with rule_path.open("rb") as stream:
            stream.seek(0,2)
            if rule_original.get("bytes")!=stream.tell():
                raise ValueError("CA_REPORT_NYSE_NONBUSINESS_RULE_BYTE_COUNT_CHANGED")
            stream.seek(0);rr=reader_type(stream)
            if len(rr.pages)!=rule_source["original_page_count"]:
                raise ValueError("CA_REPORT_NYSE_NONBUSINESS_RULE_PAGE_COUNT_CHANGED")
            page_texts=[]
            for page in pages:
                rt=rr.pages[page["page_zero_based"]].extract_text();page_texts.append(normalized(rt))
                if (rt!=page.get("text") or text_hash(rt)!=page.get("original_extract_text_sha256")
                        or raw_text(page["text_ref"]) not in (rt,rt+"\n")):
                    raise ValueError("CA_REPORT_NYSE_NONBUSINESS_ORIGINAL_RULE_PAGE_CHANGED")
        if (page_texts[0].count("Current Rule 235 provides")!=1
                or page_texts[0].count("The current rule further provides that if the record date or closing of transfer books occurs upon a day other than a business day, Rule 235 shall apply for the second preceding business day.")!=1
                or page_texts[1].count("Good Friday (variable date between Mar. 20 and April 23, both inclusive)")!=1
                or "Holidays thus affecting the ex-dividend dates are:" not in page_texts[1]):
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_CURRENT_RULE_AND_HOLIDAY_REQUIRED")
        cb=copy.deepcopy(calendar_binding)
        if (cb.get("status")!="SOURCE_BOUND_LEGAL_SESSION_CALENDAR"
                or cb.get("session_dates_sha256")!=cash._hash([str(pd.Timestamp(d).date()) for d in calendar])):
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_COMPLETE_CALENDAR_REQUIRED")
        pinned(dict(path=cb["source_reference"],sha256=cb["source_fingerprint"]))
        facts["nyse_nonbusiness_record_binding"]=dict(
            status="PINNED_NYSE_RULE235_PRE_T1_NONBUSINESS_COORDINATE",
            policy_id=cash.NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH,record_date=facts["record_date"],
            record_before_exclusive="2024-05-28",calendar_binding=cb,rule_source_ref=copy.deepcopy(rule_ref),
            original_rule_pdf_ref={k:rule_original[k] for k in ("path","sha256")},
            necessary_rule_pages=[dict(page_zero_based=p["page_zero_based"],
                original_extract_text_sha256=p["original_extract_text_sha256"],
                text_ref={k:p["text_ref"][k] for k in ("path","sha256")}) for p in pages],
            exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",strict_PIT=False)
        binding["nyse_nonbusiness_record_binding"]=copy.deepcopy(facts["nyse_nonbusiness_record_binding"])
    facts["report_frozen_cash_binding"]=binding
    return dict(id="REPORTFROZENCASH_"+_hash(facts),issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",cash_per_common_share=amount,
        cash_is_gross_announced_amount=True,currency="USD",currency_basis="INFERRED_USD_CONTEXT",
        record_date=facts["record_date"],pay_date=facts["pay_date"],publication_date=None,
        candidate_ex_date=exact[0]["effective_date"],availability_bound=dict(available_at=None),
        ordinary_cash_dividend=True,source_url=source["source_url"],source_scope=REPORT_CASH_SOURCE_SCOPE,
        historical_ex_adjudication_input=facts,report_frozen_cash_binding=binding,
        frozen_account_identity_binding=frozen_identity)


def _dated_frozen_common_unit_terms(payload,entry,*,source_ref_transport=()):
    """Three pinned source roles bind generic per-share research cash units."""
    if (payload.get("schema")!="B_FROZEN_HISTORY_DATED_NOTICE_COMMON_UNIT_BRIDGE_SOURCE_PROJECTION_V1"
            or payload.get("source_scope")!=DATED_COMMON_UNIT_SOURCE_SCOPE
            or payload.get("cash_evidence_role")!=DATED_COMMON_UNIT_ROLE
            or payload.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY"
            or payload.get("historical_available_at") is not None
            or payload.get("exchange_notice_authority")!="UNKNOWN"
            or payload.get("actual_exchange_ex_authority")!="UNKNOWN"
            or any(payload.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
        raise ValueError("CA_DATED_COMMON_UNIT_EXPLICIT_RESEARCH_ROLE_REQUIRED")
    facts=copy.deepcopy(payload["source_projection"]);exact=payload["exact_original_unsupported_keys"]
    if (facts.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY" or facts.get("available_at") is not None
            or facts.get("issuer_jurisdiction")!="US" or facts.get("security_type")!="COMMON_STOCK"
            or facts.get("currency")!="USD" or facts.get("amount_unit")!=cash.USD_PER_RAW_OLD_SHARE
            or facts.get("quantity_coordinate")!=cash.RAW_OLD_SHARE_COORDINATE
            or entry["identity_binding"]!=payload["identity_binding"]
            or entry["prior_raw_close"]!=payload["prior_raw_close"]
            or entry["original_unsupported_keys"]!=exact or len(exact)!=1
            or facts.get("exact_frozen_event_key")!=exact[0]
            or facts.get("ex_date_provenance_role")!="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY"
            or payload.get("frozen_account_identity_ref") is None):
        raise ValueError("CA_DATED_COMMON_UNIT_EXACT_FROZEN_SUBJECT_REQUIRED")
    refs=payload["source_refs"]
    def pinned(ref):
        if sum(ref==r for r in refs)!=1:raise ValueError("CA_DATED_COMMON_UNIT_NESTED_SOURCE_PIN_REQUIRED")
        target=next((tx["custody_ref"] for tx in source_ref_transport if ref==tx["original_ref"]),ref)
        return _pin(target)
    def raw_text(ref):
        with pinned(ref).open("rb") as stream:return stream.read().decode("utf-8-sig")
    def text_hash(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()
    normalized=lambda value:" ".join(value.split())
    common=_report_common_class_context(payload,entry,facts,pinned=pinned,raw_text=raw_text,text_hash=text_hash,normalized=normalized)
    frozen_identity=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=common["issuer"])
    if frozen_identity is None:raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_COM_IDENTITY_REQUIRED")
    custody_ref=payload["dated_cash_source_custody_ref"]
    source=json.loads(raw_text(custody_ref));transport_ref=source["HTTP_transport_ref"]
    transport=json.loads(raw_text(transport_ref));body_ref=source["original_HTTP_ref"]
    publication=cash._day(source["source_publication_date"],"actual_notice_header_date")
    descriptor=(source.get("source_role"),transport.get("schema"))
    generic=descriptor==("ISSUER_HOSTED_ORIGINAL_ORDINARY_CASH_DECLARATION","HISTORICAL_SOURCE_HTTP_TRANSPORT_V1")
    prefix_custody=descriptor==("OFFICIAL_ISSUER_HOSTED_HISTORICAL_DECLARATION_CASH_AND_SAME_FILE_LISTING_ONLY",
                              "ISSUER_DATED_HISTORY_ORIGINAL_HTML_TRANSPORT_V1")
    if not (generic or prefix_custody):
        raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_NOTICE_DESCRIPTOR_REQUIRED")
    if generic:
        descriptor_profile="GENERIC_ORIGINAL_HTTP_CASH_CUSTODY_DESCRIPTOR_V1"
        capture_role="ACTUAL_TRANSPORT_CURRENT_CAPTURE_UTC_NOT_PUBLICATION"
        capture=pd.Timestamp(transport["current_capture_utc"]);projection_capture=None
        original_bytes=transport.get("response_bytes")
        if (transport.get("status_code")!=200 or transport.get("url")!=source["source_url"]
                or source.get("same_source_issuer_listing_literal")!=source["source_issuer_literal"]+" (NYSE: "+facts["ticker"]+")"
                or not isinstance(source.get("same_source_US_context_literal"),str) or not source["same_source_US_context_literal"]):
            raise ValueError("CA_DATED_COMMON_UNIT_GENERIC_NOTICE_DESCRIPTOR_CHANGED")
        prefix=source["same_source_US_context_literal"]+"--(BUSINESS WIRE)-- "+source["same_source_issuer_listing_literal"]
        common_flag="cash_explicit_common_literal"
    else:
        descriptor_profile="ISSUER_DATED_HTML_CASH_PREFIX_CUSTODY_DESCRIPTOR_V1"
        capture_role="ACTUAL_TRANSPORT_HTTP_REQUEST_END_UTC_NOT_PUBLICATION"
        capture=pd.Timestamp(transport["request_end_utc"]);start=pd.Timestamp(transport["request_start_utc"])
        projection_capture=pd.Timestamp(source["current_capture_utc"])
        original_bytes=transport.get("original_HTTP_bytes")
        if (transport.get("actual_status")!=200 or transport.get("source_url")!=source["source_url"]
                or transport.get("original_HTTP_ref")!=body_ref or transport.get("source_publication_date") is not None
                or transport.get("error") is not None
                or any(transport.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
                or pd.isna(start) or start.tzinfo is None or pd.isna(projection_capture) or projection_capture.tzinfo is None
                or pd.isna(capture) or capture.tzinfo is None or start>capture or projection_capture<capture
                or source.get("ticker")!=facts["ticker"]
                or source.get("source_currency_context")!="US_LOUISVILLE_KY_ONLY_IF_PRESENT_IN_SAME_SOURCE_IDENTITY_PREFIX"
                or len(source.get("same_source_issuer_listing_prefixes",[]))!=1):
            raise ValueError("CA_DATED_COMMON_UNIT_PREFIX_NOTICE_DESCRIPTOR_CHANGED")
        identity_prefix=source["same_source_issuer_listing_prefixes"][0]
        prefix=identity_prefix["source_identity_literal"]
        parsed_prefix=re.fullmatch(r"(.+)--\(BUSINESS WIRE\)-- (.+) \(NYSE: ([A-Z0-9.\-]+)\)",prefix)
        if parsed_prefix is None or parsed_prefix.group(2)!=source["source_issuer_literal"] or parsed_prefix.group(3)!=facts["ticker"]:
            raise ValueError("CA_DATED_COMMON_UNIT_PREFIX_ISSUER_LISTING_CHANGED")
        common_flag="source_cash_explicit_common_literal"
    if (source.get("schema")!="HUM_ISSUER_ORIGINAL_ORDINARY_CASH_FRAGMENT_CUSTODY_V1"
            or source.get("source_publication_role")!="ABSOLUTE_ORIGINAL_ARTICLEDATE_PUBLISHDATE_HEADER_NOT_PRIVATE_BOARD_DAY"
            or source.get("historical_availability_authority")!="UNKNOWN" or source.get("cash_available_at") is not None
            or source.get("source_direct_ex_date") is not None
            or ("source_currency_literal" in source and source["source_currency_literal"]!="$")
            or source.get("source_currency_explicit_USD") is not False
            or any(source.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))
            or source.get("original_HTTP_sha256")!=body_ref["sha256"]
            or source.get("announcement_date")!=str(publication.date())
            or common["issuer_key"](source["source_issuer_literal"])!=common["issuer_key"](common["issuer"])
            or len(source["cash_sources"])!=1 or not source["source_url"].startswith("https://")
            or transport.get("original_HTTP_sha256")!=body_ref["sha256"]
            or transport.get("historical_availability_authority")!="UNKNOWN"
            or type(original_bytes) is not int or original_bytes<=0
            or common["fiscal"]>=publication
            or facts.get("publication_calendar_date")!=str(publication.date())
            or facts.get("issuer_source_fingerprint")!=body_ref["sha256"]
            or facts.get("identity_source_fingerprint")!=payload["frozen_account_identity_ref"]["sha256"]
            or facts.get("exchange_listing_source_reference")!=payload["report_cash_source_custody_ref"]["path"]
            or facts.get("exchange_listing_source_fingerprint")!=payload["report_cash_source_custody_ref"]["sha256"]):
        raise ValueError("CA_DATED_COMMON_UNIT_SEPARATE_SOURCE_ROLES_REQUIRED")
    if pd.isna(capture) or capture.tzinfo is None or capture<publication.tz_localize("UTC"):
        raise ValueError("CA_DATED_COMMON_UNIT_ACTUAL_CAPTURE_NOT_PUBLICATION_REQUIRED")
    row=source["cash_sources"][0]
    from scripts.storage.refresh_sec_event_originals import FilingText
    def visible(raw):
        parser=FilingText();parser.feed(raw.decode("utf-8"))
        return normalized(" ".join(parser.parts))
    with pinned(body_ref).open("rb") as stream:
        stream.seek(0,2)
        if stream.tell()!=original_bytes:
            raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_NOTICE_BYTES_CHANGED")
        def section(span):
            if (not isinstance(span,list) or len(span)!=2 or any(type(v) is not int for v in span)
                    or not 0<=span[0]<span[1] or span[1]-span[0]>65536):
                raise ValueError("CA_DATED_COMMON_UNIT_BOUNDED_ORIGINAL_RANGE_REQUIRED")
            stream.seek(span[0]);raw=stream.read(span[1]-span[0])
            if len(raw)!=span[1]-span[0]:raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_RANGE_INCOMPLETE")
            return raw
        raw=section(row["raw_byte_range"]);header=section(source["date_projection_raw_byte_range"])
        if prefix_custody:
            prefix_span=identity_prefix["raw_byte_range"]
            if (not isinstance(prefix_span,list) or len(prefix_span)!=2 or any(type(v) is not int for v in prefix_span)
                    or prefix_span[0]!=row["raw_byte_range"][0] or prefix_span[1]>row["raw_byte_range"][1]):
                raise ValueError("CA_DATED_COMMON_UNIT_IDENTITY_PREFIX_NOT_CASH_SUBJECT")
            prefix_raw=section(prefix_span)
            with pinned(identity_prefix["original_identity_prefix_ref"]).open("rb") as fragment:
                if fragment.read()!=prefix_raw:raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_IDENTITY_PREFIX_CHANGED")
            if (visible(prefix_raw)!=prefix or text_hash(prefix)!=identity_prefix["typed_content_sha256"]
                    or raw_text(identity_prefix["visible_text_ref"]) not in (prefix,prefix+"\n")):
                raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_IDENTITY_PREFIX_PROJECTION_CHANGED")
    with pinned(row["raw_fragment_ref"]).open("rb") as fragment:
        if fragment.read()!=raw:raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_CASH_FRAGMENT_CHANGED")
    literal=visible(raw);saved=raw_text(row["visible_text_ref"]);date_literal=visible(header)
    date_saved=raw_text(source["date_projection_ref"])
    if (literal!=row["dividend_paragraph"] or text_hash(literal)!=row["dividend_paragraph_typed_content_sha256"]
            or saved not in (literal,literal+"\n")
            or source["original_header_date_literal"]!=date_literal
            or date_saved not in (date_literal,date_literal+"\n",header.decode("utf-8"))
            or b'articleDate' not in header or b'publishdate' not in header
            or str(cash._day(str(pd.Timestamp(date_literal).date()),"notice_header_literal").date())!=str(publication.date())):
        raise ValueError("CA_DATED_COMMON_UNIT_ORIGINAL_DATE_OR_CASH_LITERAL_CHANGED")
    pattern=re.escape(prefix)+r" announced today that its Board of Directors has declared a cash dividend to stockholders of \$([0-9]+(?:\.[0-9]+)?) per share payable on ([A-Za-z]+ \d{1,2}, \d{4}) to stockholders of record as of the close of business on ([A-Za-z]+ \d{1,2}, \d{4})\."
    match=re.fullmatch(pattern,literal)
    if (match is None or row.get(common_flag) is not False
            or row.get("source_currency_explicit_USD") is not False or row.get("source_currency_literal")!="$"):
        raise ValueError("CA_DATED_COMMON_UNIT_GENERIC_NOTICE_NO_CLASS_OR_CURRENCY_INVENTION_REQUIRED")
    amount_literal,pay_literal,record_literal=match.groups()
    if (float(amount_literal)!=facts["cash_per_raw_share"] or row["source_cash_amount_literal"]!=amount_literal
            or str(cash._day(str(pd.Timestamp(record_literal).date()),"record_literal").date())!=facts["record_date"]
            or str(cash._day(str(pd.Timestamp(pay_literal).date()),"pay_literal",known_future_schedule=True).date())!=facts["pay_date"]
            or row["source_record_date"]!=facts["record_date"] or row["source_pay_date"]!=facts["pay_date"]):
        raise ValueError("CA_DATED_COMMON_UNIT_EXACT_NOTICE_TERMS_REQUIRED")
    for ref in refs:pinned(ref)
    binding=dict(status="PINNED_DATED_NOTICE_COMMON_UNIT_BRIDGE",cash_evidence_role=DATED_COMMON_UNIT_ROLE,
        unit_source_role=DATED_COMMON_UNIT_SCOPE["unit_source_role"],available_at=None,historical_availability_authority="UNKNOWN",
        exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
        ex_coordinate_role="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
        currency_basis="INFERRED_USD_SAME_US_COMMON_POLICY_AND_DATED_DOLLAR_NOTICE",
        security_id=facts["security_id"],ticker=facts["ticker"],listing_identity=facts["listing_identity"],currency="USD",
        cash_per_raw_share=facts["cash_per_raw_share"],record_date=facts["record_date"],pay_date=facts["pay_date"],
        notice_publication_date=str(publication.date()),private_board_declaration_date=None,
        report_publication_date=None,notice_current_capture_utc=str(capture),report_current_capture_utc=str(common["stamp"]),
        notice_descriptor_profile=descriptor_profile,notice_capture_clock_role=capture_role,
        notice_projection_capture_utc=None if projection_capture is None else str(projection_capture),
        original_notice_custody_ref=custody_ref,original_notice_body_ref=body_ref,original_notice_transport_ref=transport_ref,
        original_cash_fragment_ref=row["raw_fragment_ref"],original_header_projection_ref=source["date_projection_ref"],
        report_common_policy_custody_ref=common["custody_ref"],original_report_ref=common["original_ref"],
        original_report_cash_page_ref=common["source"]["page_text_ref"],original_report_cover_page_ref=common["full_cover_ref"],
        original_report_extractor=common["extractor"],source_common_class_literal=common["source"]["source_common_class_literal"],
        same_report_common_listing_literal=common["source"]["same_report_common_listing_literal"],
        quarterly_common_cash_policy_literal=common["source"]["cash_table_context_literal"],
        original_generic_per_share_literal=literal,frozen_account_identity_binding=copy.deepcopy(frozen_identity),
        report_currency_or_amount_not_copied_into_notice=True,amount_match_is_not_class_evidence=True,
        strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
    if prefix_custody:
        binding.update(original_notice_identity_prefix_ref=identity_prefix["original_identity_prefix_ref"],
                       original_notice_identity_prefix_text_ref=identity_prefix["visible_text_ref"])
    facts["dated_common_unit_bridge_binding"]=binding
    return dict(id="DATED_UNIT_BRIDGE_"+_hash(facts),issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",
        cash_per_common_share=facts["cash_per_raw_share"],cash_is_gross_announced_amount=True,currency="USD",
        currency_basis="INFERRED_USD_CONTEXT",record_date=facts["record_date"],pay_date=facts["pay_date"],
        publication_date=str(publication.date()),candidate_ex_date=exact[0]["effective_date"],
        availability_bound=dict(available_at=None),ordinary_cash_dividend=True,source_url=source["source_url"],
        source_scope=DATED_COMMON_UNIT_SOURCE_SCOPE,historical_ex_adjudication_input=facts,
        dated_common_unit_bridge_binding=binding,frozen_account_identity_binding=frozen_identity)


CLOSED_RECORD_RESEARCH_SCOPE = dict(POST_VERIFIED_SCOPE,
    policy_id=cash.CLOSED_RECORD_RESEARCH_POLICY,ex_coordinate_role=cash.CLOSED_RECORD_RESEARCH_ROLE,
    actual_exchange_ex_authority="UNKNOWN",clearing_delivery_day_authority="UNKNOWN",
    historical_availability_authority="UNKNOWN",original_record_date_preserved=True,
    calendar_insertion_permitted=False,due_bill_or_special_event_permitted=False)

COMPONENT_GROUP_SOURCE_SCOPE="FROZEN_PRE2026_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP"
COMPONENT_GROUP_ROLE="SOURCE_BOUND_ANNUAL_AND_QUARTERLY_COMMON_CASH_COMPONENT_GROUP"
COMPONENT_GROUP_KINDS=("ANNUAL_COMMON_SHARE_CASH_DIVIDEND","QUARTERLY_COMMON_SHARE_CASH_DIVIDEND")
COMPONENT_GROUP_SCOPE=dict(POST_VERIFIED_SCOPE,source_scope=COMPONENT_GROUP_SOURCE_SCOPE,
    cash_evidence_role=COMPONENT_GROUP_ROLE,component_kinds=list(COMPONENT_GROUP_KINDS),
    clock_applicability_role="EXPLICIT_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION",
    consumption_set_role="ORDINARY_PAY_END_CLOCK_SET_PLUS_EXPLICIT_SAME_CLOCK_COMPONENT_GROUPS",
    exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN")

BASE_VARIABLE_COMPONENT_ROLE="SOURCE_BOUND_EXPLICIT_TOTAL_BASE_AND_VARIABLE_COMMON_CASH_COMPONENT_GROUP"
BASE_VARIABLE_COMPONENT_KINDS=("QUARTERLY_BASE_COMMON_SHARE_CASH_DIVIDEND",
    "QUARTERLY_VARIABLE_PERFORMANCE_BASED_COMMON_SHARE_CASH_DIVIDEND")
BASE_VARIABLE_COMPONENT_SCOPE=dict(COMPONENT_GROUP_SCOPE,
    cash_evidence_role=BASE_VARIABLE_COMPONENT_ROLE,component_kinds=list(BASE_VARIABLE_COMPONENT_KINDS))

def _base_variable_common_statement(text, *, symbol):
    """One original common-share sentence, never an annual-rate conversion."""
    from decimal import Decimal
    day=r"([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})"
    amount=r"[$]\s*([0-9]+[.][0-9]+) per share"
    expression=(r"On "+day+r", (?P<subject>our Board|"+re.escape(symbol)
        +r"(?:[’']s Board(?: of Director(?:s|[’']s) \(Board\))?)?) declared (?:quarterly )?cash dividends totaling "
        +amount+r"(?P<pre> on (?:its|our) common stock)? \((?:including a )?"+amount
        +r" (?P<base>(?:quarterly )?base(?: cash)? dividend) and (?:a )?"+amount
        +r" (?P<variable>(?:quarterly )?variable(?:, performance-based)?(?: cash)? dividend)\)"
        +r"(?P<post> on (?:its|our) common stock)?, which (?:was|were) paid on "+day
        +r", to (?:common stockholders|common shareholders|shareholders) of record as of "+day+r"[.]")
    m=re.fullmatch(expression,text)
    if m is None or bool(m.group('pre'))==bool(m.group('post')):
        raise ValueError("CA_BASE_VARIABLE_SINGLE_COMMON_SENTENCE_REQUIRED")
    # Named captures do not alter numerical group positions. Enumerate literals
    # inside this fullmatched sentence so preferred/prior-quarter text cannot join.
    amounts=list(re.finditer(amount,text))
    if len(amounts)!=3 or any(Decimal(x.group(1))<=0 for x in amounts) or Decimal(amounts[0].group(1))!=sum((Decimal(x.group(1)) for x in amounts[1:]),Decimal(0)):
        raise ValueError("CA_BASE_VARIABLE_EXPLICIT_TOTAL_AND_TWO_COMPONENTS_REQUIRED")
    days=re.findall(day,text)
    if len(days)!=3 or not pd.Timestamp(days[0])<=pd.Timestamp(days[2])<=pd.Timestamp(days[1]):
        raise ValueError("CA_BASE_VARIABLE_DECLARATION_AND_SAME_RECORD_PAYMENT_REQUIRED")
    return dict(total=amounts[0].group(1),base=amounts[1].group(1),variable=amounts[2].group(1),
        declaration_date=str(pd.Timestamp(days[0]).date()),pay_date=str(pd.Timestamp(days[1]).date()),
        record_date=str(pd.Timestamp(days[2]).date()),subject_literal=m.group('subject'),
        private_board_declaration_date=None,component_unit_literal="per share on common stock",
        original_statement=text,component_amount_visible_spans=[[x.start(),x.end()] for x in amounts[1:]])

def _sec_base_variable_source_terms(fact, *, source, cover, bridge, locator, pinned):
    """Original byte/subject/unit proof for a fixed base/variable kind-profile."""
    from scripts.storage.refresh_sec_event_originals import FilingText
    def key(value):return re.sub(r"[\s.,-]+","",value).casefold()
    def piece(item,body_ref):
        span=item['original_byte_range'];ref=item.get('fragment_ref')
        if not isinstance(span,list) or len(span)!=2 or any(type(x) is not int for x in span) or not 0<=span[0]<span[1]<=body_ref['bytes'] or span[1]-span[0]>65536:
            raise ValueError('CA_BASE_VARIABLE_BOUNDED_ORIGINAL_FRAGMENT_REQUIRED')
        raw=pinned(ref).read_bytes()
        with pinned(body_ref).open('rb') as f:f.seek(span[0]);original=f.read(span[1]-span[0])
        if raw!=original:raise ValueError('CA_BASE_VARIABLE_ORIGINAL_BYTE_RANGE_CHANGED')
        t=FilingText();t.feed(raw.decode('utf-8'));shown=' '.join(' '.join(t.parts).split())
        if item.get('visible_text',shown)!=shown or item.get('visible_text_utf8_sha256',hashlib.sha256(shown.encode()).hexdigest())!=hashlib.sha256(shown.encode()).hexdigest():
            raise ValueError('CA_BASE_VARIABLE_VISIBLE_TEXT_CHANGED')
        return shown,raw
    if source.get('http_status')!=200 or cover.get('http_status')!=200 or cover['original_HTTP_ref']!=source['original_HTTP_ref'] or cover['source_url']!=source['source_url']:
        raise ValueError('CA_BASE_VARIABLE_EXACT_SAME_FILE_SOURCE_REQUIRED')
    if any(cover.get(k) is not False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV')) or cover.get('historical_availability')!='UNKNOWN':
        raise ValueError('CA_BASE_VARIABLE_NO_HISTORICAL_AUTHORITY_PROMOTION')
    url=source['source_url'];meta=[x for x in locator['rows'] if ('https://www.sec.gov/Archives/edgar/data/'+str(bridge['subject_CIK'])+'/'+x['adsh'].replace('-','')+'/'+x['metadata_hit_id'].split(':',1)[1])==url]
    if len(meta)!=1 or meta[0]['file_type'] not in ('10-Q','10-K') or meta[0]['file_date']!=fact['publication_calendar_date'] or not '2023-01-01'<=meta[0]['file_date']<'2026-01-01':
        raise ValueError('CA_BASE_VARIABLE_EXACT_HISTORICAL_SEC_METADATA_REQUIRED')
    roles={}
    for item in cover['identity_fragments']:
        if item['role'] in roles:raise ValueError('CA_BASE_VARIABLE_UNIQUE_COVER_ROLE_REQUIRED')
        shown,raw=piece(item,source['original_HTTP_ref']);roles[item['role']]=(shown,raw)
    issuer=roles['REGISTRANT_NAME'][0];symbol=roles['REGISTERED_TRADING_SYMBOL'][0]
    if (symbol!=fact['original_candidate_unsupported_key']['ticker'] or not re.fullmatch(_US_CHARTER_STATE_NAMES,roles['US_CHARTER_STATE'][0])
        or roles['REGISTERED_SECURITY_EXCHANGE'][0]!='The New York Stock Exchange'
        or not roles['REGISTERED_SECURITY_TITLE'][0].startswith('Common Stock, par value $')
        or not re.fullmatch(r'Title of each class Trading Symbol\(s\) Name of each exchange on which registered Common Stock, par value [$][0-9.]+ per share '+re.escape(symbol)+r' The New York Stock Exchange',roles['REGISTERED_COMMON_LISTING_TABLE'][0])
        ):
        raise ValueError('CA_BASE_VARIABLE_SAME_FILE_US_COMMON_AND_USD_SHARE_UNIT_REQUIRED')
    import xml.etree.ElementTree as ET
    ns='{http://www.xbrl.org/2003/instance}'
    unit=ET.fromstring('<proof xmlns:xbrli="http://www.xbrl.org/2003/instance">'+roles['USD_PER_SHARE_XBRL_UNIT_DEFINITION'][1].decode('utf-8')+'</proof>')[0]
    numerator=unit.find(ns+'divide/'+ns+'unitNumerator/'+ns+'measure');denominator=unit.find(ns+'divide/'+ns+'unitDenominator/'+ns+'measure')
    if unit.tag!=ns+'unit' or numerator is None or denominator is None or numerator.text!='iso4217:USD' or denominator.text!='xbrli:shares':
        raise ValueError('CA_BASE_VARIABLE_TRUE_USD_DIVIDED_BY_SHARE_UNIT_REQUIRED')
    btext,_=piece(bridge['subject_cover'],bridge['original_HTTP_ref'])
    pattern=r'Name of issuer: (.+?) Title of Class of Securities: (Common Stock) CUSIP Number: ([0-9A-Z]{9}) Date of Event'
    bm=re.search(pattern,btext)
    if (bridge.get('schema')!='B_EXACT_CUSIP_OFFICIAL_SUBJECT_COMMON_STOCK_AND_FROZEN_SHARE_DESCRIPTOR_V1' or bm is None
        or bm.group(1)!=bridge['subject_issuer_literal'] or bm.group(2)!=bridge['subject_common_class_literal'] or bm.group(3)!=bridge['subject_CUSIP']
        or key(bm.group(1))!=key(issuer) or bridge['actual_SEC_filed_date']>=fact['original_candidate_unsupported_key']['effective_date']
        or bridge.get('historical_available_at') is not None or bridge.get('historical_availability_authority')!='UNKNOWN'
        or any(bridge.get(k) is not False for k in ('original_frozen_class_rewritten','share_quantity_effect','membership_interval_extension','new_security_master','ticker_alias','strict_PIT','production_qualified','quote_qualified','certified_NAV'))):
        raise ValueError('CA_BASE_VARIABLE_EXACT_CUSIP_SOURCE_COMMON_SUBJECT_REQUIRED')
    witness=json.loads(pinned(bridge['official_original_SH_descriptor_witness_ref']).read_text(encoding='utf-8'))
    from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
    ws=witness['necessary_three_distinct_source_filing_witnesses']
    if len(ws)!=3 or len({x['original_identity_row']['ACCESSION_NUMBER'] for x in ws})!=3:
        raise ValueError('CA_BASE_VARIABLE_THREE_DISTINCT_OFFICIAL_SHARE_WITNESSES_REQUIRED')
    for item in ws:
        row=item['original_identity_row'];sub=item['original_submission_metadata_row']
        if (row['CUSIP']!=bridge['subject_CUSIP'] or row['SSHPRNAMTTYPE']!='SH' or row['PUTCALL'] is not None or key(row['NAMEOFISSUER'])!=key(issuer)
            or row['ACCESSION_NUMBER']!=sub['ACCESSION_NUMBER'] or sub['PERIODOFREPORT']!='31-MAR-2023' or not pd.Timestamp('2023-01-01')<=pd.Timestamp(sub['FILING_DATE'])<pd.Timestamp('2024-01-01')
            or content_hash(row)!=item['original_identity_row_typed_content_sha256'] or content_hash(sub)!=item['original_submission_metadata_row_typed_content_sha256']):
            raise ValueError('CA_BASE_VARIABLE_ORIGINAL_13F_SHARE_UNIT_WITNESS_REQUIRED')
    cashitem=fact['selected_original_cash_fragment'];text,cashraw=piece(cashitem,source['original_HTTP_ref'])
    if text!=pinned(cashitem['visible_text_ref']).read_text(encoding='utf-8') or text.count(fact['selected_original_cash_statement'])!=1:
        raise ValueError('CA_BASE_VARIABLE_ORIGINAL_CASH_STATEMENT_UNIQUE_REQUIRED')
    t=_base_variable_common_statement(fact['selected_original_cash_statement'],symbol=symbol)
    tags=list(re.finditer(rb'<ix:nonFraction\s+([^>]+)>([0-9.]+)</ix:nonFraction>',cashraw))
    if len(tags)!=3:raise ValueError('CA_BASE_VARIABLE_THREE_EXACT_CASH_AMOUNT_TAGS_REQUIRED')
    for i,tag in enumerate(tags):
        attrs=dict(re.findall(rb'([A-Za-z]+)="([^"]+)"',tag.group(1)))
        if (attrs.get(b'unitRef',b'').decode()!=unit.attrib['id'] or attrs.get(b'scale')!=b'0'
            or attrs.get(b'name')!=(b'us-gaap:CommonStockDividendsPerShareDeclared' if i==0 else attrs.get(b'name',b'').split(b':')[0]+(b':CommonStockDividendsPerShareBaseCash' if i==1 else b':CommonStockDividendsPerShareVariableCash'))
            or tag.group(2).decode()!=t[('total','base','variable')[i]]):
            raise ValueError('CA_BASE_VARIABLE_AMOUNT_TAG_AND_SAME_FILE_USD_SHARE_UNIT_REQUIRED')
    if any(t[a]!=fact[b] for a,b in (('total','source_declared_total_amount_literal'),('record_date','source_record_date'),('pay_date','source_payment_date'),('declaration_date','source_company_declaration_date'))):
        raise ValueError('CA_BASE_VARIABLE_CAPTURED_TERMS_CHANGED')
    literals=bridge.get('original_frozen_class_literals')
    if not isinstance(literals,list) or len(literals)!=1 or not any(' '.join(x['original_identity_row']['TITLEOFCLASS'].split())==' '.join(literals[0].split()) for x in witness['necessary_three_distinct_source_filing_witnesses']):
        raise ValueError('CA_BASE_VARIABLE_EXACT_SOURCE_FROZEN_DESCRIPTOR_WITNESS_REQUIRED')
    t.update(issuer=issuer,ticker=symbol,listing='NYSE:'+symbol,currency='USD',publication=fact['publication_calendar_date'],source_url=url,original_frozen_class_literal=literals[0],
        cash_fragment_ref=cashitem['fragment_ref'],cash_text_ref=cashitem['visible_text_ref'],source_CUSIP=bridge['subject_CUSIP'],original_HTTP_ref=source['original_HTTP_ref'])
    return t

def _sec_base_variable_component_group_terms(payload,entry,*,source_ref_transport=()):
    """New kind-profile of the existing one-credit component owner."""
    from decimal import Decimal
    facts=copy.deepcopy(payload['source_projection']);exact=payload['exact_original_unsupported_keys'];refs=payload['source_refs']
    checked={}
    def pinned(ref):
        if sum(ref==x for x in refs)!=1:raise ValueError('CA_BASE_VARIABLE_EXACT_SOURCE_PIN_REQUIRED')
        target=next((tx['custody_ref'] for tx in source_ref_transport if tx['original_ref']==ref),ref)
        k=(target['path'],target['sha256']);path=Path(target['path'])
        def signature():
            st=path.stat();return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
        if k not in checked:checked[k]=(_pin(target),signature())
        if signature()!=checked[k][1]:raise ValueError('CA_BASE_VARIABLE_PIN_STAT_CHANGED')
        return checked[k][0]
    if (payload.get('schema')!='B_FROZEN_HISTORY_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_SOURCE_PROJECTION_V1'
        or payload.get('source_scope')!=COMPONENT_GROUP_SOURCE_SCOPE or payload.get('cash_evidence_role')!=BASE_VARIABLE_COMPONENT_ROLE
        or payload.get('clock_role')!='POST_VERIFIED_ACCOUNTING_ONLY' or facts.get('clock_role')!='POST_VERIFIED_ACCOUNTING_ONLY'
        or payload.get('historical_available_at') is not None or facts.get('available_at') is not None
        or any(payload.get(k)!='UNKNOWN' for k in ('exchange_notice_authority','actual_exchange_ex_authority'))
        or any(payload.get(k) is not False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
        or entry['identity_binding']!=payload['identity_binding'] or entry['prior_raw_close']!=payload['prior_raw_close']
        or entry['original_unsupported_keys']!=exact or len(exact)!=1 or facts.get('exact_frozen_event_key')!=exact[0]
        or facts.get('ordinary_cash_confirmed') is not False or facts.get('common_cash_component_group_confirmed') is not True
        or facts.get('ex_date_provenance_role')!='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY'):
        raise ValueError('CA_BASE_VARIABLE_EXPLICIT_ACCOUNTING_KIND_PROFILE_REQUIRED')
    group=json.loads(pinned(payload['component_group_source_ref']).read_text(encoding='utf-8'))
    if (group.get('schema')!='B_SEC_ORIGINAL_EXPLICIT_TOTAL_BASE_VARIABLE_COMMON_CASH_COMPONENT_GROUP_V1'
        or group.get('account_credit_count')!=1 or type(group.get('account_credit_count')) is not int
        or group.get('components_are_not_separate_account_credits') is not True
        or group.get('historical_availability_authority')!='UNKNOWN'
        or any(group.get(k) is not False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))):
        raise ValueError('CA_BASE_VARIABLE_EXACT_SINGLE_CREDIT_GROUP_SOURCE_REQUIRED')
    fact=group['source_fact'];source=json.loads(pinned(fact['source_custody_ref']).read_text(encoding='utf-8'))
    cover=json.loads(pinned(fact['same_file_cash_identity_support_ref']).read_text(encoding='utf-8'))
    bridge=json.loads(pinned(fact['source_common_CUSIP_identity_custody_ref']).read_text(encoding='utf-8'))
    locator=json.loads(pinned(fact['historical_sec_filing_metadata_ref']).read_text(encoding='utf-8'))
    t=_sec_base_variable_source_terms(fact,source=source,cover=cover,bridge=bridge,locator=locator,pinned=pinned)
    if fact['original_candidate_unsupported_key']!=exact[0] or fact['frozen_account_identity_ref']!=payload['frozen_account_identity_ref'] or bridge['exact_original_frozen_identity_ref']!=payload['frozen_account_identity_ref']:
        raise ValueError('CA_BASE_VARIABLE_EXACT_FROZEN_SOURCE_RELATION_REQUIRED')
    class_binding=dict(status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',source_common_class_literal='Common Stock',source_CUSIP=t['source_CUSIP'],source_common_CUSIP_identity_custody_ref=fact['source_common_CUSIP_identity_custody_ref'],original_frozen_class_literal=t['original_frozen_class_literal'],no_class_alias=True,original_frozen_class_rewritten=False)
    identity=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer'],source_common_class_binding=class_binding)
    if identity is None or identity['original_source_row']['cusip']!=t['source_CUSIP']:
        raise ValueError('CA_BASE_VARIABLE_EXACT_ORIGINAL_CUSIP_RAW_SHARE_RELATION_REQUIRED')
    components=[]
    for index,(kind,rate) in enumerate(zip(BASE_VARIABLE_COMPONENT_KINDS,(t['base'],t['variable']))):
        cr=fact['independent_component_fact_refs'][index];part=json.loads(pinned(cr).read_text(encoding='utf-8'))
        if (part['component_kind']!=kind or part['source_amount_literal']!=rate or part['cash_custody_ref']!=fact['source_custody_ref'] or part['cash_fragment_ref']!=t['cash_fragment_ref']
            or part['same_record_date']!=t['record_date'] or part['same_pay_date']!=t['pay_date'] or part['component_is_not_separate_account_credit'] is not True
            or part['source_component_literal'] not in fact['selected_original_cash_statement']):
            raise ValueError('CA_BASE_VARIABLE_TWO_INDEPENDENT_SOURCE_COMPONENTS_REQUIRED')
        components.append(dict(component_kind=kind,source_amount_literal=rate,source_component_literal=part['source_component_literal'],independent_component_fact_ref=cr,
            security_id=facts['security_id'],ticker=t['ticker'],currency='USD',record_date=t['record_date'],pay_date=t['pay_date'],ex_date=exact[0]['effective_date'],
            amount_unit=cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=cash.RAW_OLD_SHARE_COORDINATE,component_is_not_separate_account_credit=True))
    if (facts['ticker']!=t['ticker'] or facts['listing_identity']!=t['listing'] or facts['currency']!='USD' or facts['issuer_jurisdiction']!='US'
        or facts['security_type']!='COMMON_STOCK' or facts['amount_unit']!=cash.USD_PER_RAW_OLD_SHARE or facts['quantity_coordinate']!=cash.RAW_OLD_SHARE_COORDINATE
        or facts['record_date']!=t['record_date'] or facts['pay_date']!=t['pay_date'] or Decimal(str(facts['cash_per_raw_share']))!=Decimal(t['total'])
        or facts['publication_calendar_date']!=t['publication']):raise ValueError('CA_BASE_VARIABLE_EXACT_PROJECTION_UNIT_TERMS_REQUIRED')
    binding=dict(status='PINNED_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP',cash_evidence_role=BASE_VARIABLE_COMPONENT_ROLE,
        amount_aggregation_role='EXPLICIT_ORIGINAL_TOTAL_EQUALS_TWO_DECIMAL_COMPONENTS_CREDIT_ONCE',total_cash_amount_literal=t['total'],cash_components=components,
        group_id=_hash(dict(components=components,original_key=exact[0])),original_exact_key=exact[0],
        cash_per_raw_share=float(t['total']),security_id=facts['security_id'],ticker=t['ticker'],listing_identity=t['listing'],currency='USD',record_date=t['record_date'],pay_date=t['pay_date'],ex_date=exact[0]['effective_date'],publication_calendar_date=t['publication'],
        private_board_declaration_date=None,source_company_declaration_date=t['declaration_date'],actual_SEC_filed_date=t['publication'],current_capture_utc=source['capture_utc'],available_at=None,
        historical_availability_authority='UNKNOWN',exchange_notice_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',
        component_group_source_ref=payload['component_group_source_ref'],original_source_custody_ref=fact['source_custody_ref'],original_cash_fragment_ref=t['cash_fragment_ref'],original_cash_text_ref=t['cash_text_ref'],original_full_HTTP_ref=t['original_HTTP_ref'],
        same_file_cash_identity_support_ref=fact['same_file_cash_identity_support_ref'],source_common_CUSIP_identity_custody_ref=fact['source_common_CUSIP_identity_custody_ref'],
        clock_applicability_role=COMPONENT_GROUP_SCOPE['clock_applicability_role'],consumption_set_role=COMPONENT_GROUP_SCOPE['consumption_set_role'],accounting_clock_convention=CLOCK,
        annual_ordinary_or_quarterly_reclassification=False,frozen_account_identity_binding=identity,issuer_name_alias_used=False,original_frozen_issuer_literal=identity['original_source_row']['issuer_name'],source_legal_issuer_literal=t['issuer'],
        strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
    facts['cash_component_group_binding']=binding
    return dict(id='SOURCE_COMPONENT_GROUP:'+binding['group_id'],issuer=entry['identity_binding']['issuer'],listing_identity=t['listing'],security_type='COMMON_STOCK',cash_per_common_share=float(t['total']),cash_is_gross_announced_amount=True,currency='USD',currency_basis='EXPLICIT_USD',record_date=t['record_date'],pay_date=t['pay_date'],publication_date=t['publication'],candidate_ex_date=exact[0]['effective_date'],availability_bound=dict(available_at=None),source_url=t['source_url'],source_scope=COMPONENT_GROUP_SOURCE_SCOPE,cash_component_group=True,cash_component_group_binding=binding,frozen_account_identity_binding=identity,ex_directly_declared=False,source_declared_ex_date=None,historical_ex_adjudication_input=facts)


def _common_cash_component_group_terms(payload,entry,*,source_ref_transport=()):
    """A fixed annual/quarterly source group books one summed raw-share claim."""
    if payload.get('cash_evidence_role')==BASE_VARIABLE_COMPONENT_ROLE:
        return _sec_base_variable_component_group_terms(payload,entry,source_ref_transport=source_ref_transport)
    from decimal import Decimal
    flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
    facts=copy.deepcopy(payload["source_projection"]);exact=payload["exact_original_unsupported_keys"]
    closed_ref=payload.get("closed_record_research_binding_ref")
    if (payload.get("schema")!="B_FROZEN_HISTORY_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_SOURCE_PROJECTION_V1"
            or payload.get("source_scope")!=COMPONENT_GROUP_SOURCE_SCOPE or payload.get("cash_evidence_role")!=COMPONENT_GROUP_ROLE
            or payload.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY" or payload.get("historical_available_at") is not None
            or payload.get("exchange_notice_authority")!="UNKNOWN" or payload.get("actual_exchange_ex_authority")!="UNKNOWN"
            or any(payload.get(k) is not False for k in flags)
            or facts.get("clock_role")!="POST_VERIFIED_ACCOUNTING_ONLY" or facts.get("available_at") is not None
            or facts.get("ordinary_cash_confirmed") is not False or facts.get("common_cash_component_group_confirmed") is not True
            or facts.get("issuer_jurisdiction")!="US" or facts.get("security_type")!="COMMON_STOCK"
            or facts.get("currency")!="USD" or facts.get("amount_unit")!=cash.USD_PER_RAW_OLD_SHARE
            or facts.get("quantity_coordinate")!=cash.RAW_OLD_SHARE_COORDINATE
            or entry["identity_binding"]!=payload["identity_binding"] or entry["prior_raw_close"]!=payload["prior_raw_close"]
            or exact!=entry["original_unsupported_keys"] or len(exact)!=1 or facts.get("exact_frozen_event_key")!=exact[0]
            or facts.get("ex_date_provenance_role")!=(cash.CLOSED_RECORD_RESEARCH_ROLE if closed_ref is not None else "EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY")
            or payload.get("frozen_account_identity_ref") is None):
        raise ValueError("CA_EXPLICIT_SAME_CLOCK_COMPONENT_GROUP_REQUIRED")
    refs=payload["source_refs"]
    def pinned(ref):
        if sum(ref==r for r in refs)!=1:raise ValueError("CA_COMPONENT_GROUP_EXACT_SOURCE_PIN_REQUIRED")
        target=next((tx["custody_ref"] for tx in source_ref_transport if tx["original_ref"]==ref),ref)
        return _pin(target)
    def raw_text(ref):
        with pinned(ref).open("rb") as stream:return stream.read().decode("utf-8-sig")
    def text_hash(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()
    group_ref=payload["component_group_source_ref"];group=json.loads(raw_text(group_ref))
    source_ref=group["source_custody_ref"];source=json.loads(raw_text(source_ref))
    native_closed=closed_ref is not None and source.get("schema")=="PGR_ISSUER_ORIGINAL_COMMON_CASH_FRAGMENT_SET_CUSTODY_V1"
    clock_visible=None
    if native_closed:
        fragments=source.get("cash_fragments")
        if not isinstance(fragments,list) or len(fragments)!=2:
            raise ValueError("CA_CLOSED_RECORD_TWO_NATIVE_CASH_FRAGMENTS_REQUIRED")
        from scripts.storage.refresh_sec_event_originals import FilingText
        normalized=lambda value:" ".join(value.split())
        visibles=[]
        for fragment in fragments:
            span=fragment["source_original_byte_range"];raw_ref=fragment["raw_fragment_ref"]
            if (not isinstance(span,list) or len(span)!=2 or any(type(v) is not int for v in span)
                    or not 0<=span[0]<span[1]<=source["original_HTTP_bytes"] or span[1]-span[0]>65536):
                raise ValueError("CA_CLOSED_RECORD_NATIVE_FRAGMENT_RANGE_CHANGED")
            with pinned(raw_ref).open("rb") as stream:fragment_raw=stream.read()
            parser=FilingText();parser.feed(fragment_raw.decode("utf-8"))
            visible=normalized(" ".join(parser.parts));literal=fragment["original_literal"]
            if (len(fragment_raw)!=span[1]-span[0] or raw_ref.get("bytes")!=len(fragment_raw)
                    or visible!=normalized(literal) or raw_text(fragment["visible_text_ref"]) not in (literal,literal+"\n")
                    or text_hash(literal)!=fragment.get("original_typed_text_sha256")
                    or fragment.get("original_typed_text_recipe")!="UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT"
                    or re.search(r"\b(?:preferred|depositary|ADS|special|liquidat\w*|merger\w*|due.bill)\b",visible,re.I)):
                raise ValueError("CA_CLOSED_RECORD_NATIVE_FRAGMENT_TEXT_CHANGED")
            visibles.append(visible)
        if fragments[0]["source_original_byte_range"][1]>fragments[1]["source_original_byte_range"][0]:
            raise ValueError("CA_CLOSED_RECORD_NATIVE_FRAGMENT_OVERLAP")
        declaration=re.search(r"On ([A-Za-z]+ \d{1,2}, \d{4}), the Board of Directors of (.+?) \(NYSE:\s*([A-Z0-9.\-]+)\) declared an (annual common share dividend, in the amount of \$([0-9]+(?:\.[0-9]+)?) per share), and a (quarterly common share dividend, in the amount of \$([0-9]+(?:\.[0-9]+)?) per share)\.",visibles[0])
        common_clock=re.search(r"Both the annual and quarterly dividends are payable ([A-Za-z]+ \d{1,2}, \d{4}), to shareholders of record at the close of business on ([A-Za-z]+ \d{1,2}, \d{4})\.",visibles[1])
        dateline=re.match(r"(.+?), ([A-Za-z.]+ \d{1,2}, \d{4}) \(GLOBE NEWSWIRE\) -- ",visibles[0])
        if (declaration is None or common_clock is None or dateline is None
                or re.search(r"ex.dividend|due.bill",visibles[1],re.I)
                or re.search(r", (?:"+_US_CHARTER_STATE_NAMES+r")$",dateline.group(1),re.I) is None
                or source.get("actual_status")!=200
                or source.get("source_publication_clock_role")!="ACTUAL_ORIGINAL_VISIBLE_HEADER_DATELINE_NOT_FEED_OR_PRIVATE_BOARD_DATE"
                or str(pd.Timestamp(dateline.group(2)).date())!=source["source_publication_date"]
                or declaration.group(3)!=source["ticker"]
                or group.get("original_cash_fragments")!=[f["raw_fragment_ref"] for f in fragments]
                or group.get("common_clock_fragment_ref")!=fragments[1]["raw_fragment_ref"]
                or group.get("common_clock_text_ref")!=fragments[1]["visible_text_ref"]):
            raise ValueError("CA_CLOSED_RECORD_NATIVE_CLASSES_AND_CLOCKS_REQUIRED")
        # Pure projection from pinned original fragments, not custody mutation.
        source=dict(source,original_cash_fragment_ref=fragments[0]["raw_fragment_ref"],
            text_projection_ref=fragments[0]["visible_text_ref"],source_original_byte_range=fragments[0]["source_original_byte_range"],
            dividend_paragraph=fragments[0]["original_literal"],dividend_paragraph_typed_content_sha256=fragments[0]["original_typed_text_sha256"],
            private_board_declaration_date=str(pd.Timestamp(declaration.group(1)).date()),issuer_literal=declaration.group(2),
            listing_literal="NYSE:"+declaration.group(3),source_record_date=str(pd.Timestamp(common_clock.group(2)).date()),
            source_pay_date=str(pd.Timestamp(common_clock.group(1)).date()),source_direct_ex_date=None,
            same_document_US_context_literal=dateline.group(1),actual_HTTP_status=source["actual_status"],
            source_role="ISSUER_HOSTED_ORIGINAL_CASH_DECLARATION",components_aggregated=False,
            publication_date_role="ORIGINAL_VISIBLE_DATELINE_NOT_PRIVATE_BOARD_DATE",source_currency_literal="$",explicit_USD_literal_present=False,
            cash_components=[dict(component_kind=kind,distinct_component=True,amount=declaration.group(5 if i==0 else 7),
                amount_literal="$"+declaration.group(5 if i==0 else 7)+" per share",
                unit_literal=("annual" if i==0 else "quarterly")+" common share dividend") for i,kind in enumerate(COMPONENT_GROUP_KINDS)])
        clock_visible=visibles[1]
    raw_ref=source["original_cash_fragment_ref"];text_ref=source["text_projection_ref"]
    span=source["source_original_byte_range"]
    closed_binding=None
    if closed_ref is not None:
        if not native_closed:
            raise ValueError("CA_CLOSED_RECORD_NATIVE_EX_ABSENT_SOURCE_PROFILE_REQUIRED")
        closed_binding=json.loads(raw_text(closed_ref))
        cash.validate_closed_record_research_binding(closed_binding,
            record_date=facts["record_date"],pay_date=facts["pay_date"],ex_date=exact[0]["effective_date"],
            security_id=facts["security_id"],ticker=facts["ticker"],original_key=exact[0])
        if closed_binding["source_cash_custody_ref"]!=source_ref:
            raise ValueError("CA_CLOSED_RECORD_CASH_CUSTODY_PIN_CHANGED")
        closure=json.loads(raw_text(closed_binding["official_closure_source_ref"]))
        body_ref=closed_binding["official_closure_original_HTTP_ref"]
        if (closure.get("schema")!="NYSE_OFFICIAL_SPECIAL_MARKET_CLOSURE_SOURCE_CUSTODY_V1"
                or closure.get("status_code")!=200 or closure.get("closed_date")!=facts["record_date"]
                or closure.get("closure_scope")!="NYSE_GROUP_EQUITY_AND_OPTIONS_MARKETS"
                or closure.get("original_HTTP_ref")!=body_ref
                or closure.get("source_role")!="ORIGINAL_DATED_NYSE_PRESS_RELEASE_PRIMARY_HTTP_OPAQUE_BODY"
                or not closure.get("source_url","").startswith("https://ir.theice.com/")
                or any(closure.get(k) is not False for k in flags)
                or closure.get("historical_availability_authority")!="UNKNOWN"
                or closure.get("independent_dividend_ex_authority")!="UNKNOWN"
                or closure.get("clearing_or_bank_delivery_day_authority")!="UNKNOWN"):
            raise ValueError("CA_CLOSED_RECORD_OFFICIAL_CLOSURE_SOURCE_REQUIRED")
        if cash._day(closure["source_publication_date"],"closure_publication")>=cash._day(facts["record_date"],"closed_record"):
            raise ValueError("CA_CLOSED_RECORD_CLOSURE_DATE_CONFLICT")
        span_closed=closure["original_closed_day_literal_byte_range"];literal=closure["original_closed_day_literal"]
        if (not isinstance(span_closed,list) or len(span_closed)!=2 or any(type(v) is not int for v in span_closed)
                or not 0<=span_closed[0]<span_closed[1]<=body_ref["bytes"] or span_closed[1]-span_closed[0]>4096
                or re.fullmatch(r"will close all NYSE Group equity and options markets on [A-Za-z]+, [A-Za-z]+ \d{1,2}, \d{4}",literal) is None
                or str(pd.Timestamp(literal.split(" on ",1)[1]).date())!=facts["record_date"]):
            raise ValueError("CA_CLOSED_RECORD_EXACT_OFFICIAL_LITERAL_REQUIRED")
        with pinned(body_ref).open("rb") as stream:
            stream.seek(span_closed[0]);selected=stream.read(span_closed[1]-span_closed[0])
        if selected!=literal.encode("ascii") or hashlib.sha256(selected).hexdigest()!=closure["original_closed_day_literal_bytes_sha256"]:
            raise ValueError("CA_CLOSED_RECORD_ORIGINAL_CLOSURE_BYTES_CHANGED")
        independent_refs=group.get("independent_component_fact_refs")
        if independent_refs is not None:
            if (not isinstance(independent_refs,list) or len(independent_refs)!=2 or independent_refs[0]==independent_refs[1]
                    or closed_binding.get("independent_component_fact_refs")!=independent_refs
                    or closed_binding.get("component_group_source_ref")!=group_ref):
                raise ValueError("CA_CLOSED_RECORD_EXACT_TWO_INDEPENDENT_COMPONENT_FACT_REFS_REQUIRED")
            for part,component_ref in zip(group["cash_components"],independent_refs):
                fact=json.loads(raw_text(component_ref))
                expected=dict(schema="B_ORIGINAL_COMMON_CASH_DIVIDEND_COMPONENT_SOURCE_FACT_V1",
                    source_component=part,source_custody_ref=source_ref,record_date=facts["record_date"],
                    pay_date=facts["pay_date"],source_declared_ex_date=None,original_frozen_research_coordinate=exact[0]["effective_date"],
                    publication_calendar_date=source["source_publication_date"],private_board_declaration_date=source["private_board_declaration_date"],
                    component_is_not_separate_account_credit=True,historical_availability_authority="UNKNOWN",
                    strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
                if any(type(fact.get(k)) is not type(v) or fact.get(k)!=v for k,v in expected.items()):
                    raise ValueError("CA_CLOSED_RECORD_INDEPENDENT_COMPONENT_SOURCE_FACT_CHANGED")
        calendar_ref=closed_binding["calendar_binding"]["calendar_source_ref"]
        calendar_path=pinned(calendar_ref)
        if calendar_path.suffix.lower()==".parquet":
            import pyarrow.parquet as pq
            with calendar_path.open("rb") as stream:
                parquet=pq.ParquetFile(stream)
                for calendar_index in range(parquet.metadata.num_row_groups):
                    calendar_group=parquet.metadata.row_group(calendar_index)
                    calendar_column=next(calendar_group.column(j) for j in range(calendar_group.num_columns) if calendar_group.column(j).path_in_schema=="trade_date")
                    if calendar_column.statistics is None or pd.Timestamp(calendar_column.statistics.max)>=pd.Timestamp(closed_binding["scope_end_exclusive"]):
                        raise ValueError("CA_CLOSED_RECORD_PRE2026_CALENDAR_FOOTER_REQUIRED")
                stream.seek(0)
                rows=pq.read_table(stream,columns=["trade_date"],filters=[("trade_date",">=",pd.Timestamp(closed_binding["scope_start"])),("trade_date","<",pd.Timestamp(closed_binding["scope_end_exclusive"]))]).column("trade_date").to_pylist()
            calendar_source={"calendar":[str(pd.Timestamp(d).date()) for d in rows]}
        else:
            calendar_source=json.loads(raw_text(calendar_ref))
        if calendar_source.get("calendar")!=closed_binding["calendar_binding"]["session_dates"]:
            raise ValueError("CA_CLOSED_RECORD_ORIGINAL_CALENDAR_SOURCE_CHANGED")
    publication=cash._day(source["source_publication_date"],"component_publication")
    private=cash._day(source["private_board_declaration_date"],"component_private_board")
    capture=pd.Timestamp(source["capture_utc"])
    if (group.get("schema") not in (("PGR_ORIGINAL_COMMON_CASH_FIXED_COMPONENT_GROUP_SOURCE_PROJECTION_V1","B_ORIGINAL_COMMON_CASH_FIXED_COMPONENT_GROUP_SOURCE_PROJECTION_V1") if native_closed else ("PGR_ORIGINAL_COMMON_CASH_FIXED_COMPONENT_GROUP_SOURCE_PROJECTION_V1",))
            or not native_closed and source.get("schema")!="PGR_ISSUER_ORIGINAL_MULTI_COMPONENT_COMMON_CASH_CUSTODY_V1"
            or source.get("source_role")!="ISSUER_HOSTED_ORIGINAL_CASH_DECLARATION"
            or source.get("actual_HTTP_status")!=200 or group.get("actual_HTTP_status")!=200
            or source.get("original_HTTP_ref") is not None or group.get("original_HTTP_ref") is not None
            or source.get("full_HTTP_widgets_not_decoded_or_persisted") is not True
            or source.get("components_aggregated") is not False
            or source.get("publication_date_role")!="ORIGINAL_VISIBLE_DATELINE_NOT_PRIVATE_BOARD_DATE"
            or source.get("historical_availability_authority")!="UNKNOWN" or group.get("historical_availability_authority")!="UNKNOWN"
            or any(obj.get(k) is not False for obj in (group,source) for k in flags)
            or group.get("component_group_is_not_an_ordinary_quarterly_dividend") is not True
            or group.get("source_unit")!="ORIGINAL_COMMON_SHARE_CASH_PER_SHARE"
            or group.get("original_key")!=exact[0] or not native_closed and source.get("original_key")!=exact[0]
            or group.get("original_cash_fragment_ref")!=raw_ref or group.get("cash_text_projection_ref")!=text_ref
            or group.get("original_HTTP_opaque_sha256")!=source["original_HTTP_sha256"]
            or group.get("original_HTTP_opaque_bytes")!=source["original_HTTP_bytes"]
            or group.get("actual_capture_utc")!=source["capture_utc"]
            or group.get("private_board_declaration_date")!=source["private_board_declaration_date"]
            or group.get("publication_calendar_date")!=source["source_publication_date"]
            or group.get("record_date")!=source["source_record_date"] or group.get("pay_date")!=source["source_pay_date"]
            or group.get("source_direct_ex_date")!=source["source_direct_ex_date"]
            or source.get("ticker")!=facts["ticker"] or source.get("listing_literal")!="NYSE:"+facts["ticker"]
            or not source["source_url"].startswith("https://")
            or source.get("source_currency_literal")!="$" or source.get("explicit_USD_literal_present") is not False
            or pd.isna(capture) or capture.tzinfo is None or capture<publication.tz_localize("UTC") or private>publication
            or type(source.get("original_HTTP_bytes")) is not int
            or not isinstance(span,list) or len(span)!=2 or any(type(v) is not int for v in span)
            or not 0<=span[0]<span[1]<=source["original_HTTP_bytes"] or span[1]-span[0]>65536
            or facts.get("publication_calendar_date")!=source["source_publication_date"]
            or facts.get("record_date")!=source["source_record_date"] or facts.get("pay_date")!=source["source_pay_date"]
            or (source["source_direct_ex_date"] is not None if closed_ref is not None else source["source_direct_ex_date"]!=exact[0]["effective_date"])
            or facts.get("issuer_source_fingerprint")!=raw_ref["sha256"]
            or facts.get("identity_source_fingerprint")!=payload["frozen_account_identity_ref"]["sha256"]
            or facts.get("exchange_listing_source_reference")!=source_ref["path"]
            or facts.get("exchange_listing_source_fingerprint")!=source_ref["sha256"]):
        raise ValueError("CA_COMPONENT_GROUP_ORIGINAL_PARTIAL_CUSTODY_AND_CLOCKS_REQUIRED")
    cash._sha(source["original_HTTP_sha256"],"opaque_original_HTTP")
    with pinned(raw_ref).open("rb") as stream:raw=stream.read()
    if len(raw)!=span[1]-span[0] or (raw_ref.get("bytes") is not None and raw_ref["bytes"]!=len(raw)):
        raise ValueError("CA_COMPONENT_GROUP_ORIGINAL_FRAGMENT_BYTES_CHANGED")
    from scripts.storage.refresh_sec_event_originals import FilingText
    parser=FilingText();parser.feed(raw.decode("utf-8"))
    normalized=lambda value:" ".join(value.split())
    literal=source["dividend_paragraph"];visible=normalized(" ".join(parser.parts))
    if (visible!=normalized(literal) or text_hash(literal)!=source["dividend_paragraph_typed_content_sha256"]
            or raw_text(text_ref) not in (literal,literal+"\n")
            or re.search(r"\b(?:preferred|depositary|ADS|special|liquidat\w*|merger\w*)\b",visible,re.I)):
        raise ValueError("CA_COMPONENT_GROUP_ORIGINAL_COMMON_CASH_TEXT_CHANGED")
    declaration=re.search(r"On ([A-Za-z]+ \d{1,2}, \d{4}), the Board of Directors of (.+?) \(NYSE:\s*([A-Z0-9.\-]+)\) declared an (annual common share dividend, in the amount of \$([0-9]+(?:\.[0-9]+)?) per share), and a (quarterly common share dividend, in the amount of \$([0-9]+(?:\.[0-9]+)?) per share)\.",visible)
    common_clock=(re.search(r"Both the annual and quarterly dividends are payable ([A-Za-z]+ \d{1,2}, \d{4}), to shareholders of record at the close of business on ([A-Za-z]+ \d{1,2}, \d{4})\.",clock_visible) if native_closed else
        re.search(r"Both the annual and quarterly dividends are payable ([A-Za-z]+ \d{1,2}, \d{4}), to shareholders of record at the close of business on ([A-Za-z]+ \d{1,2}, \d{4}) \(ex-dividend date of ([A-Za-z]+ \d{1,2}, \d{4})\)\.",visible))
    dateline=re.match(re.escape(source["same_document_US_context_literal"])+r", ([A-Za-z.]+ \d{1,2}, \d{4}) \(GLOBE NEWSWIRE\) -- ",visible)
    if (declaration is None or common_clock is None or dateline is None
            or str(pd.Timestamp(declaration.group(1)).date())!=source["private_board_declaration_date"]
            or declaration.group(2)!=source["issuer_literal"] or declaration.group(3)!=facts["ticker"]
            or str(pd.Timestamp(dateline.group(1)).date())!=source["source_publication_date"]
            or [str(pd.Timestamp(value).date()) for value in common_clock.groups()]!=
                ([source["source_pay_date"],source["source_record_date"]] if native_closed else [source["source_pay_date"],source["source_record_date"],source["source_direct_ex_date"]])):
        raise ValueError("CA_COMPONENT_GROUP_TWO_CLASSES_AND_COMMON_DATES_REQUIRED")
    expected_literals=(declaration.group(4),declaration.group(6))
    expected_amounts=(declaration.group(5),declaration.group(7))
    parts=group["cash_components"];original_parts=source["cash_components"]
    if len(parts)!=2 or len(original_parts)!=2:
        raise ValueError("CA_COMPONENT_GROUP_COMPLETE_TWO_LEGS_REQUIRED")
    component_fields={"component_kind","source_amount_literal","source_component_literal","component_original_bytes_sha256",
        "local_fragment_byte_range","original_HTTP_byte_range","source_custody_ref","original_cash_fragment_ref","cash_text_projection_ref"}
    components=[];ranges=[]
    for index,(part,original,kind) in enumerate(zip(parts,original_parts,COMPONENT_GROUP_KINDS)):
        local=part["local_fragment_byte_range"]
        if (set(part)!=component_fields or part.get("component_kind")!=kind or original.get("component_kind")!=kind
                or original.get("distinct_component") is not True or part.get("source_component_literal")!=expected_literals[index]
                or part.get("source_amount_literal")!=expected_amounts[index] or original.get("amount")!=expected_amounts[index]
                or original.get("amount_literal")!="$"+expected_amounts[index]+" per share"
                or original.get("unit_literal")!=("annual" if index==0 else "quarterly")+" common share dividend"
                or part.get("source_custody_ref")!=source_ref or part.get("original_cash_fragment_ref")!=raw_ref
                or part.get("cash_text_projection_ref")!=text_ref
                or not isinstance(local,list) or len(local)!=2 or any(type(v) is not int for v in local)
                or not 0<=local[0]<local[1]<=len(raw)
                or part.get("original_HTTP_byte_range")!=[span[0]+local[0],span[0]+local[1]]):
            raise ValueError("CA_COMPONENT_GROUP_DISTINCT_RAW_COMMON_LEGS_REQUIRED")
        selected=raw[local[0]:local[1]]
        if selected.decode("utf-8")!=expected_literals[index] or hashlib.sha256(selected).hexdigest()!=part["component_original_bytes_sha256"]:
            raise ValueError("CA_COMPONENT_GROUP_ORIGINAL_COMPONENT_BYTES_CHANGED")
        if ranges and local[0]<ranges[-1][1]:raise ValueError("CA_COMPONENT_GROUP_OVERLAPPING_OR_REPEATED_LEG")
        ranges.append(local)
        components.append(dict(part,component_id=_hash(part),currency="USD",amount_unit=cash.USD_PER_RAW_OLD_SHARE,
            quantity_coordinate=cash.RAW_OLD_SHARE_COORDINATE,security_id=facts["security_id"],ticker=facts["ticker"],
            record_date=facts["record_date"],pay_date=facts["pay_date"],ex_date=exact[0]["effective_date"],
            date_binding_role="SAME_SOURCE_BOTH_COMPONENTS_COMMON_DATE_CLAUSE"))
    total=sum((Decimal(value) for value in expected_amounts),Decimal("0"))
    if (total<=0 or type(facts.get("cash_per_raw_share")) not in (int,float) or facts["cash_per_raw_share"]!=float(total)):
        raise ValueError("CA_COMPONENT_GROUP_EXACT_DECIMAL_SUM_REQUIRED")
    identity=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry["identity_binding"]["issuer"])
    if identity is None:raise ValueError("CA_COMPONENT_GROUP_EXISTING_RAW_COM_IDENTITY_REQUIRED")
    original_row=identity["original_source_row"]
    if not pd.Timestamp(original_row["effective_start"])<=publication<=pd.Timestamp(original_row["effective_end"]):
        raise ValueError("CA_COMPONENT_GROUP_SOURCE_LISTING_NOT_IN_ORIGINAL_FROZEN_IDENTITY_INTERVAL")
    for ref in refs:pinned(ref)
    binding=dict(status="PINNED_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP",cash_evidence_role=COMPONENT_GROUP_ROLE,
        group_id=_hash(dict(components=components,original_key=exact[0])),cash_components=components,original_exact_key=exact[0],
        component_group_source_ref=group_ref,original_source_custody_ref=source_ref,original_cash_fragment_ref=raw_ref,
        original_cash_text_ref=text_ref,opaque_HTTP_sha256=source["original_HTTP_sha256"],opaque_HTTP_bytes=source["original_HTTP_bytes"],
        original_full_HTTP_ref=None,partial_custody_role="EXACT_CAPTURED_BYTE_FRAGMENT_WITH_OPAQUE_WHOLE_BODY_COMMITMENT_NOT_RETAINED_FULL_BODY",
        amount_aggregation_role="EXACT_ORIGINAL_DECIMAL_STRINGS_SUM_ONCE_PER_RAW_COMMON_SHARE",
        total_cash_amount_literal=format(total,"f"),cash_per_raw_share=float(total),security_id=facts["security_id"],ticker=facts["ticker"],
        listing_identity=facts["listing_identity"],currency="USD",record_date=facts["record_date"],pay_date=facts["pay_date"],
        ex_date=exact[0]["effective_date"],publication_calendar_date=source["source_publication_date"],private_board_declaration_date=source["private_board_declaration_date"],
        current_capture_utc=str(capture),available_at=None,historical_availability_authority="UNKNOWN",
        exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
        clock_applicability_role=COMPONENT_GROUP_SCOPE["clock_applicability_role"],consumption_set_role=COMPONENT_GROUP_SCOPE["consumption_set_role"],
        accounting_clock_convention=CLOCK,annual_ordinary_or_quarterly_reclassification=False,
        currency_basis="INFERRED_USD_SAME_SOURCE_US_COMMON_SHARE_COMPONENTS",frozen_account_identity_binding=identity,
        source_legal_issuer_literal=source["issuer_literal"],original_frozen_issuer_literal=original_row["issuer_name"],
        issuer_relation_role="EXACT_RESOLVED_FROZEN_SYMBOL_COMMON_CLASS_RAW_SHARE_COORDINATE_NOT_NAME_EQUIVALENCE",
        issuer_name_alias_used=False,
        strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
    if closed_binding is not None:
        facts["closed_record_research_binding"]=closed_binding
        binding.update(closed_record_research_binding_ref=closed_ref,
            independent_component_fact_refs=copy.deepcopy(group.get("independent_component_fact_refs")),
            original_cash_fragments=group["original_cash_fragments"],common_clock_fragment_ref=group["common_clock_fragment_ref"],
            common_clock_text_ref=group["common_clock_text_ref"],native_source_schema="PGR_ISSUER_ORIGINAL_COMMON_CASH_FRAGMENT_SET_CUSTODY_V1")
    facts["cash_component_group_binding"]=binding
    return dict(id="SOURCE_COMPONENT_GROUP:"+binding["group_id"],issuer=entry["identity_binding"]["issuer"],
        listing_identity=facts["listing_identity"],security_type="COMMON_STOCK",cash_per_common_share=float(total),
        cash_is_gross_announced_amount=True,currency="USD",currency_basis="INFERRED_USD_CONTEXT",record_date=facts["record_date"],
        pay_date=facts["pay_date"],publication_date=source["source_publication_date"],candidate_ex_date=exact[0]["effective_date"],
        availability_bound=dict(available_at=None),source_url=source["source_url"],source_scope=COMPONENT_GROUP_SOURCE_SCOPE,
        cash_component_group=True,cash_component_group_binding=binding,frozen_account_identity_binding=identity,
        ex_directly_declared=closed_binding is None,source_declared_ex_date=source["source_direct_ex_date"],historical_ex_adjudication_input=facts,
        **(dict(closed_record_research_binding=closed_binding) if closed_binding is not None else {}))



_US_CHARTER_STATE_NAMES=("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
        "District of Columbia|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|"
        "Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|"
        "Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|"
        "North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|"
        "South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
        "West Virginia|Wisconsin|Wyoming")

FROZEN_COMMON_NAMESPACE_ROLE="EXACT_FROZEN_COM_RAW_COMMON_CASH_NAMESPACE_NO_ISSUER_NAME_ALIAS"
FROZEN_COMMON_NAMESPACE_SCOPE=dict(POST_VERIFIED_SCOPE,
    identity_transport_role=FROZEN_COMMON_NAMESPACE_ROLE,
    identity_publication_authority="UNKNOWN_NO_AVAILABLE_TIME_TRANSPORT",
    source_class_binding="ORIGINAL_DECLARATION_EXACT_LISTED_SYMBOL_AND_COMMON_SHARE",
    accounting_label_role="ORIGINAL_FROZEN_ISSUER_LABEL_SEPARATE_FROM_SOURCE_LEGAL_NAME")


DATED_COMMON_DECLARATION_ROLE="SAME_ORIGINAL_DATED_REGULAR_COMMON_CASH_DECLARATION"
_US_STATE_POSTAL_ABBREVIATIONS="AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"

SEC_PARENT_EXHIBIT_COMMON_ROLE="SAME_ACCESSION_SEC_PARENT_COMMON_AMOUNT_AND_LINKED_EX99_DATES"
SEC_PARENT_EXHIBIT_COMMON_PROFILE="SEC_8K_EXPLICIT_COMMON_DECLARATION_WITH_SAME_ACCESSION_EX99_RECORD_PAYMENT_CORROBORATION"


def _sec_parent_exhibit_common_cash_terms(fact,*,source,pinned,projection,pub,capture,header_ref,locator_ref=None):
    """Explicit common amount in parent and separately linked same-accession dates.

    Original paragraphs remain separate; this produces research accounting terms,
    never a fabricated single-file clause or historical availability authority.
    """
    from decimal import Decimal
    from urllib.parse import urljoin
    from scripts.storage.refresh_sec_event_originals import FilingText
    flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
    if (fact.get("source_profile")!=SEC_PARENT_EXHIBIT_COMMON_PROFILE
            or fact.get("status")!="DIRECT_COMMON_AMOUNT_SOURCE_FACT_COMPLETED_NOT_BINDER_ADMISSION"
            or any(fact.get(k) is not False for k in flags)
            or fact.get("historical_available_at") is not None or fact.get("historical_availability_authority")!="UNKNOWN"
            or fact.get("fragments_concatenated_or_relabelled_same_paragraph") is not False
            or fact.get("main_document_contains_record_payment_complete_terms") is not False
            or fact.get("annualized_amount_division_used") is not False
            or fact.get("source_publication_date")!=str(pub.date())):
        raise ValueError("CA_SEC_PARENT_EXHIBIT_EXPLICIT_SEPARATE_RESEARCH_ROLES_REQUIRED")
    parents=[];urls=[];metadata=[]
    for prefix,kind in (("main_8K","8-K"),("exhibit_99_1","EX-99.1")):
        original=fact[prefix+"_original_http_ref"];transport=json.loads(pinned(fact[prefix+"_capture_ref"]).read_text(encoding="utf-8"))
        md=transport.get("original_sec_locator_row",{});url=transport.get("source_url","")
        metadata_role="ORIGINAL_HTTP_CAPTURE_LOCATOR_ROW"
        if not md:
            if locator_ref is None:raise ValueError("CA_SEC_PARENT_EXHIBIT_EXPLICIT_EXISTING_LOCATOR_REQUIRED")
            locator=json.loads(pinned(locator_ref).read_text(encoding="utf-8"))
            rows=[r for r in locator.get("selected_rows",[]) if r.get("source_url")==url]
            if (locator.get("schema")!="B_PRE2026_EXACT_ISSUER_SEP_FILING_METADATA_LOCATOR_PROJECTION_V1"
                    or locator.get("historical_availability_authority")!="UNKNOWN"
                    or any(locator.get(k) is not False for k in ("strict_PIT","quote_qualified","certified_NAV"))
                    or locator.get("no_body_or_highlights_evaluation") is not True or len(rows)!=1):
                raise ValueError("CA_SEC_PARENT_EXHIBIT_EXACT_EXISTING_LOCATOR_ROW_REQUIRED")
            locator_capture=json.loads(pinned(locator["source_capture_ref"]).read_text(encoding="utf-8"))
            if (locator_capture.get("schema")!="B_DATE_BOUNDED_HISTORICAL_SEC_FILING_METADATA_CAPTURE_V1"
                    or locator_capture.get("http_status")!=200 or any(locator_capture.get(k) is not False for k in flags)
                    or locator_capture.get("received_http_bytes_sha256")!=locator_capture["opaque_original_http_ref"]["sha256"]
                    or locator_capture.get("received_bytes")!=pinned(locator_capture["opaque_original_http_ref"]).stat().st_size
                    or locator_capture.get("highlights_body_not_read_or_used") is not True
                    or locator_capture.get("current_index_is_not_historical_acquisition_vintage") is not True):
                raise ValueError("CA_SEC_PARENT_EXHIBIT_PINNED_EXISTING_LOCATOR_CAPTURE_REQUIRED")
            md=rows[0];metadata_role="SEPARATE_EXISTING_PINNED_LOCATOR_NOT_ORIGINAL_HTTP_CAPTURE_FIELD"
        path=re.fullmatch(r"https://www[.]sec[.]gov/Archives/edgar/data/([0-9]+)/([0-9]{18})/([^/?#]+)",url)
        stamp=pd.Timestamp(transport.get("retrieved_at_utc"))
        if (transport.get("schema")!="B_HISTORICAL_PRIMARY_HTTP_SOURCE_CAPTURE_V1" or transport.get("http_status")!=200
                or transport.get("original_http_bytes_ref")!=original
                or transport.get("received_http_bytes_sha256")!=original.get("sha256")
                or transport.get("received_bytes")!=original.get("bytes")
                or any(transport.get(k) is not False for k in flags) or transport.get("historical_available_at") is not None
                or ((metadata_role=="ORIGINAL_HTTP_CAPTURE_LOCATOR_ROW" and transport.get("original_acquisition_vintage")!="UNKNOWN")
                    or (metadata_role!="ORIGINAL_HTTP_CAPTURE_LOCATOR_ROW" and transport.get("historical_availability_authority")!="UNKNOWN")) or path is None
                or md.get("file_type")!=kind or md.get("source_url")!=url or md.get("file_date")!=str(pub.date())
                or (metadata_role=="ORIGINAL_HTTP_CAPTURE_LOCATOR_ROW" and transport.get("actual_file_date_from_current_historical_metadata")!=str(pub.date()))
                or md.get("adsh","").replace("-","")!=path.group(2)
                or md.get("actual_filename_from_original_hit_id")!=path.group(3)
                or md.get("original_hit_id")!=md.get("adsh","")+":"+path.group(3)
                or len(md.get("ciks",[]))!=1 or int(md["ciks"][0])!=int(path.group(1))
                or pd.isna(stamp) or stamp.tzinfo is None or stamp<pub.tz_localize("UTC")):
            raise ValueError("CA_SEC_PARENT_EXHIBIT_EXACT_CAPTURE_URL_ACCESSION_AND_CLOCK_REQUIRED")
        parents.append(pinned(original));urls.append(url);metadata.append(dict(md,metadata_role=metadata_role))
    if (metadata[0]["adsh"]!=metadata[1]["adsh"] or metadata[0]["ciks"]!=metadata[1]["ciks"]
            or metadata[0].get("display_names")!=metadata[1].get("display_names")):
        raise ValueError("CA_SEC_PARENT_EXHIBIT_SAME_ACCESSION_SUBJECT_REQUIRED")
    def original_part(parent,item,*,link=False):
        rng=item["original_byte_range"];r=item["original_fragment_ref" if link else "fragment_ref"]
        if (not isinstance(rng,list) or len(rng)!=2 or any(type(n) is not int for n in rng)
                or not 0<=rng[0]<rng[1]<=parent.stat().st_size or rng[1]-rng[0]>16384):
            raise ValueError("CA_SEC_PARENT_EXHIBIT_EXACT_BOUNDED_ORIGINAL_RANGE_REQUIRED")
        with parent.open("rb") as h:h.seek(rng[0]);part=h.read(rng[1]-rng[0])
        if (part!=pinned(r).read_bytes() or hashlib.sha256(part).hexdigest()!=r["sha256"]
                or (not link and item.get("original_substring_sha256")!=r["sha256"])):
            raise ValueError("CA_SEC_PARENT_EXHIBIT_ORIGINAL_FRAGMENT_BYTES_REQUIRED")
        if link:return part.decode("utf-8")
        parser=FilingText();parser.feed(part.decode("utf-8"));text=" ".join(" ".join(parser.parts).split())
        if text!=item["visible_text"] or hashlib.sha256(text.encode()).hexdigest()!=item.get("visible_text_utf8_sha256"):
            raise ValueError("CA_SEC_PARENT_EXHIBIT_ORIGINAL_VISIBLE_TEXT_REQUIRED")
        return text
    link=fact["same_accession_original_ex99_link"]
    shown_link=original_part(parents[0],link,link=True)
    anchors=re.findall(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>([^<]+)</a>',shown_link,re.I)
    hrefs=[a[0] for a in anchors]
    if (link.get("original_source_ref")!=fact["main_8K_original_http_ref"] or hrefs!=[link.get("literal_href")]
            or urljoin(urls[0],hrefs[0])!=urls[1] or link.get("literal_target_url")!=urls[1]):
        raise ValueError("CA_SEC_PARENT_EXHIBIT_ORIGINAL_99_1_HREF_REQUIRED")
    main=original_part(parents[0],fact["main_8K_common_amount_fragment"])
    exhibit=original_part(parents[1],fact["exhibit_99_1_record_payment_fragment"])
    declaration=re.search(r'On ([A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}), (.+?) (?:\(the "Company"\) )?issued a press release announcing',main)
    amounts=list(re.finditer(r'declared a regular quarterly dividend of \$([0-9]+[.][0-9]+) per common share, which press release is attached as Exhibit 99[.]1 to this Item 7[.]01 of this Current Report on Form 8-K and incorporated by reference herein[.]',main))
    dates=re.fullmatch(r'The new quarterly dividend of \$([0-9]+[.][0-9]+) per share, up from \$([0-9]+[.][0-9]+) per share, is payable on ([A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}), to shareholders of record as of ([A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})[.] The ex-dividend date is ([A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})[.]',exhibit)
    contexts=source.get("same_source_identity_context_fragments",[]);currency=source.get("same_source_US_context_fragments",[])
    if len(contexts)!=1 or len(currency)!=1 or dates is None or declaration is None or len(amounts)!=1:
        raise ValueError("CA_SEC_PARENT_EXHIBIT_UNIQUE_COMMON_AMOUNT_AND_DATES_REQUIRED")
    # The cash action belongs to this issuer's board, not merely another amount
    # mentioned in the same issuer filing. The optional increase clause is an
    # original explanatory clause; its annualized amount is never used as cash.
    public_day=pub.strftime("%B ")+str(pub.day)+pub.strftime(", %Y")
    issuer_prefix=(r'On '+re.escape(public_day)+r', '+re.escape(declaration.group(2))
        +r' (?:\(the "Company"\) )?issued a press release announcing that its Board of Directors '
        +r'(?:has increased the Company[\x27\u2019]s regular quarterly dividend by [0-9]+[.][0-9]+% to an annualized rate of \$[0-9]+[.][0-9]+ per share, and )?')
    if re.fullmatch(issuer_prefix,main[:amounts[0].start()]) is None:
        raise ValueError("CA_SEC_PARENT_EXHIBIT_DECLARING_BOARD_SUBJECT_REQUIRED")
    issuer_context=projection(contexts[0]);us_context=projection(currency[0])
    subject=re.match(r'The Board of Directors of '+re.escape(declaration.group(2))+r'(?: (\([A-Z][A-Z0-9]{1,9}\)))? \((NYSE|NASDAQ):\s*([A-Z][A-Z0-9.]*)\) ',issuer_context)
    dateline=re.fullmatch(r'[A-Z][A-Z .\'-]+, ('+_US_STATE_POSTAL_ABBREVIATIONS+r')[.]?--\(BUSINESS WIRE\)--([A-Z][a-z]{2}[.]? [0-9]{1,2}, 20[0-9]{2})-- Regulatory News:',us_context)
    original_texts=[projection(p) for p in source.get("cash_fragments",[])]
    issuer=declaration.group(2);anchor_title=issuer+" Press Release, dated "+pub.strftime("%B ")+str(pub.day)+pub.strftime(", %Y")+" (furnished pursuant to Item 7.01)."
    if len(anchors)!=1 or anchors[0][1]!=anchor_title:raise ValueError("CA_SEC_PARENT_EXHIBIT_SAME_DECLARATION_ORIGINAL_RELEASE_LINK_REQUIRED")
    amount=Decimal(amounts[0].group(1));record=cash._day(dates.group(4),"original_exhibit_record");pay=cash._day(dates.group(3),"original_exhibit_pay",known_future_schedule=True);ex=cash._day(dates.group(5),"original_exhibit_ex")
    if (subject is None or dateline is None
            or cash._day(dateline.group(2),"original_issuer_dateline")!=pub or cash._day(declaration.group(1),"original_8K_public_announcement")!=pub
            or len(original_texts)!=1 or original_texts[0]!=exhibit
            or not amount.is_finite() or amount<=0 or Decimal(dates.group(1))!=amount
            or fact.get("source_cash_amount_literal")!=amounts[0].group(1)
            or Decimal(str(fact.get("source_cash_amount_per_declared_common_share")))!=amount
            or fact.get("source_common_unit_literal")!="per common share" or fact.get("source_currency_literal")!="$"
            or (fact.get("source_record_date"),fact.get("source_payment_date"),fact.get("source_direct_ex_date"))!=(str(record.date()),str(pay.date()),str(ex.date()))
            or (fact["original_candidate_unsupported_key"]["ticker"],fact["original_candidate_unsupported_key"]["effective_date"])!=(subject.group(3),str(ex.date()))
            or not pub<=ex<=record<=pay or record>=pd.Timestamp("2026-01-01")
            or [" ".join(v.split()) for v in metadata[0].get("display_names",[])]!=[issuer+" ("+subject.group(3)+") (CIK "+metadata[0]["ciks"][0]+")"]):
        raise ValueError("CA_SEC_PARENT_EXHIBIT_EXACT_ISSUER_COMMON_AMOUNT_AND_CLOCK_REQUIRED")
    typed=lambda text:hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return dict(issuer=issuer,ticker=subject.group(3),listing=subject.group(2)+":"+subject.group(3),amount=float(amount),currency_basis="INFERRED_USD_CONTEXT",
        record=str(record.date()),pay=str(pay.date()),publication=str(pub.date()),available=None,
        body_ref=copy.deepcopy(fact["main_8K_common_amount_fragment"]["fragment_ref"]),header_ref=copy.deepcopy(header_ref),source_paragraph=main,primary_source_url=urls[0],issuer_corrob_source_url=source["source_url"],
        source_original_typed_text_digest=typed(main),source_original_typed_text_digest_recipe="UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT",
        source_declared_ex_date=None,source_US_context_literal=us_context,source_issuer_self_identification_parenthetical_literal=subject.group(1),issuer_parenthetical_is_not_frozen_identity_alias=True,source_issuer_listing_literal=issuer+" ("+subject.group(2)+": "+subject.group(3)+")",
        original_source_unit_literal="per common share",source_common_cover_class_literal=None,
        source_full_HTTP_sha256=fact["main_8K_original_http_ref"]["sha256"],source_full_HTTP_bytes=fact["main_8K_original_http_ref"]["bytes"],full_HTTP_body_locally_available=True,
        current_transport_capture_utc=str(capture.tz_convert("UTC")),capture_is_not_available_at=True,historical_availability_authority="UNKNOWN",
        actual_exchange_ex_authority="UNKNOWN",actual_SEC_HTTP_custody_verified=True,SEC_header_historical_availability_authority="UNKNOWN",source_subject_role=SEC_PARENT_EXHIBIT_COMMON_ROLE,
        source_publication_date_role="ORIGINAL_8K_STATED_PUBLIC_RELEASE_DAY_AND_METADATA_FILE_DATE_NOT_PRIVATE_BOARD_DAY",private_board_declaration_date=None,
        source_paragraph_terms_role="ORIGINAL_PARENT_COMMON_AMOUNT_ONLY_NOT_COMPLETE_RECORD_PAY_CLAUSE",complete_terms_same_original_paragraph=False,
        source_declaring_subject_literal="its Board of Directors",declared_common_amount_bound_to_original_issuer=True,
        linked_exhibit_original_paragraph=exhibit,linked_exhibit_typed_text_digest=typed(exhibit),linked_exhibit_original_ref=copy.deepcopy(fact["exhibit_99_1_record_payment_fragment"]["fragment_ref"]),
        linked_exhibit_actual_ex_literal=str(ex.date()),independent_exchange_ex_authority="UNKNOWN",linked_parent_exhibit_source_fact=copy.deepcopy(fact),
        parent_and_exhibit_locator_roles=[m["metadata_role"] for m in metadata],separate_existing_locator_ref=copy.deepcopy(locator_ref))


def _original_dated_common_cash_terms(source,*,pinned,same_file_identity_source=None,source_custody_ref=None,frozen_original_issuer_literal=None,sec_parent_exhibit_fact=None,sec_parent_exhibit_locator_ref=None,separate_common_binding=None,fixed_annual_common_binding=None):
    """Read the declared common-cash clause from physically pinned article fragments.

    The full HTTP SHA is an opaque capture commitment when only selected bytes
    were persisted. Neither it nor current capture grants historical availability.
    """
    from decimal import Decimal
    from scripts.storage.refresh_sec_event_originals import FilingText
    annual=fixed_annual_common_binding is not None
    if annual:
        if (source.get("schema_version")!="B_HISTORICAL_ISSUER_ORIGINAL_ARTICLE_FRAGMENT_CAPTURE_V1"
                or source.get("capture_profile")!="EXACT_ORIGINAL_HTTP_ARTICLE_SUBRANGE_NOT_FULL_HTTP_BODY"
                or source.get("full_HTTP_response_locally_available") is not False
                or source.get("source_sec_same_file_submission_header_claim") is not False
                or any(source.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
            raise ValueError("CA_DATED_ANNUAL_ORIGINAL_HTTP_FRAGMENT_ROLE_REQUIRED")
    if (not annual and source.get("schema_version")!="B_HISTORICAL_PRIMARY_SOURCE_CAPTURE_V1"
            or not ((source.get("capture_profile")=="DATED_ISSUER_PRIMARY_HTML_BOUNDED_CASH_AND_DATED_HEADER_ORIGINAL_HTTP_FRAGMENTS"
                and all(source.get(k) is False for k in ("strict_pit_qualified","quote_qualified","certified_nav_qualified")))
                or (source.get("source_sec_same_file_submission_header_claim") is False
                and all(source.get(k) is False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))))
            or source.get("http_status")!=200
            or not re.fullmatch(r"[0-9a-f]{64}",source.get("received_http_bytes_sha256",""))
            or type(source.get("received_bytes")) is not int or source["received_bytes"]<=0
            or not source.get("source_url","").startswith("https://")
            or source.get("historical_availability_status")!="UNKNOWN"
):
        raise ValueError("CA_DATED_COMMON_ORIGINAL_FRAGMENT_CUSTODY_REQUIRED")
    full_ref=source.get("original_article_fragment_ref") if annual else source.get("original_http_bytes_ref");full_body=None
    if full_ref is not None:
        if (not isinstance(full_ref,dict) or full_ref.get("sha256")!=source["received_http_bytes_sha256"]
                or (not annual and full_ref.get("bytes")!=source["received_bytes"])):
            raise ValueError("CA_DATED_COMMON_FULL_BODY_COMMITMENT_REQUIRED")
        full_body=pinned(full_ref).read_bytes()
        if len(full_body)!=source["received_bytes"] or hashlib.sha256(full_body).hexdigest()!=source["received_http_bytes_sha256"]:
            raise ValueError("CA_DATED_COMMON_FULL_BODY_COMMITMENT_REQUIRED")
    def projection(item,*,header=False):
        ref=item["fragment_ref"];rng=item["original_byte_range"];raw=pinned(ref).read_bytes()
        if not (isinstance(rng,list) and len(rng)==2 and all(type(v) is int for v in rng)
                and 0<=rng[0]<rng[1]<=source["received_bytes"] and rng[1]-rng[0]==len(raw)<=16384):
            raise ValueError("CA_DATED_COMMON_ORIGINAL_BOUNDED_RANGE_REQUIRED")
        if full_body is not None and full_body[rng[0]:rng[1]]!=raw:
            raise ValueError("CA_DATED_COMMON_ORIGINAL_FRAGMENT_BODY_MISMATCH")
        parser=FilingText();parser.feed(raw.decode("utf-8"));text=" ".join(" ".join(parser.parts).split())
        if text!=item["literal" if header else "visible_text"]:
            raise ValueError("CA_DATED_COMMON_ORIGINAL_TEXT_CHANGED")
        if not header and hashlib.sha256(text.encode("utf-8")).hexdigest()!=item.get("visible_text_utf8_sha256"):
            raise ValueError("CA_DATED_COMMON_ORIGINAL_TEXT_CHANGED")
        return text
    headers=[]
    for item in source.get("dated_header_observations",[]):
        if item not in headers:headers.append(item)
    if len(headers)!=1:raise ValueError("CA_DATED_COMMON_UNIQUE_ABSOLUTE_HEADER_REQUIRED")
    header=projection(headers[0],header=True)
    annual_header=re.fullmatch(r"([A-Z][a-z]{2} [0-9]{1,2}, 20[0-9]{2}), [0-9]{2}:[0-9]{2} ET",header) if annual else None
    if not (annual_header is not None or (not annual and re.fullmatch(r"(?:[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}|20[0-9]{2}-[0-9]{2}-[0-9]{2}|[0-9]{2}/[0-9]{2}/20[0-9]{2})",header))):
        raise ValueError("CA_DATED_COMMON_ABSOLUTE_HEADER_REQUIRED")
    pub=cash._day(annual_header.group(1) if annual else header,"original_article_header_date");capture=pd.Timestamp(source["retrieval_timestamp_utc"])
    if (pub>=pd.Timestamp("2026-01-01") or pd.isna(capture) or capture.tzinfo is None
            or capture<pub.tz_localize("UTC") or source.get("publication_date_expected_from_original_dated_source",source.get("source_publication_calendar_date"))!=str(pub.date())):
        raise ValueError("CA_DATED_COMMON_TRUE_HEADER_DATE_REQUIRED")
    if annual:
        bound=fixed_annual_common_binding
        if (same_file_identity_source is not None or sec_parent_exhibit_fact is not None or separate_common_binding is not None
                or bound.get("status")!="PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT"
                or bound.get("fixed_single_annual_payment") is not True or bound.get("annualized_rate_conversion") is not False
                or bound.get("no_class_alias") is not True or bound.get("original_frozen_class_rewritten") is not False):
            raise ValueError("CA_DATED_ANNUAL_EXACT_COMMON_MONETARY_SUPPORT_REQUIRED")
        contexts=source.get("same_source_identity_context_fragments",[])
        if full_body is None or len(contexts)!=1 or len(source.get("cash_fragments",[]))!=1:
            raise ValueError("CA_DATED_ANNUAL_ONE_ORIGINAL_ARTICLE_SUBJECT_REQUIRED")
        dateline=projection(contexts[0]);item=source["cash_fragments"][0];text=projection(item)
        transport=json.loads(pinned(source["capture_original_metadata_ref"]).read_text(encoding="utf-8"))
        normalized_name=lambda v:re.sub(r"[\s.,]+","",v).casefold()
        if (transport.get("url")!=source["source_url"] or transport.get("status_code")!=200
                or transport.get("full_response_retained") is not False
                or transport.get("raw_capture_kind")!="exact HTTP response byte fragment from historical H1 through SOURCE closing paragraph"
                or transport.get("sha256")!=source["original_article_fragment_ref"]["sha256"]
                or transport.get("raw_byte_count")!=len(full_body) or transport.get("public_timestamp_literal")!=header
                or transport.get("original_fragment_offset")!=source.get("original_http_response_fragment_offset")
                or normalized_name(transport.get("news_provided_by",""))!=normalized_name(bound["source_legal_issuer_literal"])):
            raise ValueError("CA_DATED_ANNUAL_ORIGINAL_ISSUER_DISTRIBUTION_CAPTURE_REQUIRED")
        subject=re.match(r'[A-Z][A-Z .\'-]+\s*, (?P<day>[A-Z][a-z]{2}[.]? [0-9]{1,2}, 20[0-9]{2}) /PRNewswire/ -- \((?P<venue>NYSE AMERICAN|NYSE|NASDAQ|CBOE): (?P<ticker>[A-Z][A-Z0-9.]*)\) (?P<issuer>[^()]+?) \("(?P<alias>[^"()]+)" or the "Company"\)',dateline)
        key=lambda v:re.sub(r"[\s.,]+","",v).casefold()
        if (subject is None or key(subject.group("issuer"))!=key(frozen_original_issuer_literal or "")
                or cash._day(subject.group("day").replace(".",""),"annual_same_article_dateline")!=pub
                or subject.group("venue").replace(" ","_")+":"+subject.group("ticker")!=bound["source_listing_identity"]
                or source.get("full_HTTP_response_locally_available") is not False):
            raise ValueError("CA_DATED_ANNUAL_ORIGINAL_LISTED_ISSUER_SUBJECT_REQUIRED")
        declaration=(re.escape(subject.group("alias"))+r" declares annual dividend of (?P<sign>[$])(?P<amount>[0-9]+[.][0-9]+) per (?P<ticker>[A-Z][A-Z0-9.]*) share "
            r"Declaration date is (?P<decl>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}) "
            r"Ex-dividend date is (?P<issuer_ex>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}) "
            r"Record date is (?P<record>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}) "
            r"Payable date is (?P<pay>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})")
        matches=list(re.finditer(declaration,text));m=matches[0] if len(matches)==1 else None
        if (m is None or m.end()!=len(text) or m.group("ticker")!=subject.group("ticker")
                or cash._day(m.group("decl"),"annual_declared_public_day")!=pub
                or "Annual Dividend Declaration" not in text[:m.start()]):
            raise ValueError("CA_DATED_ANNUAL_FIXED_SINGLE_PAYMENT_LITERAL_REQUIRED")
        amount=Decimal(m.group("amount"));record=cash._day(m.group("record"),"annual_record");pay=cash._day(m.group("pay"),"annual_pay",known_future_schedule=True)
        observed=cash._day(m.group("issuer_ex"),"annual_issuer_observed_ex")
        if (not amount.is_finite() or amount<=0 or amount!=Decimal(str(bound["common_amount"]))
                or str(record.date())!=bound["common_record_date"] or not pub<=observed<=record<=pay
                or record>=pd.Timestamp("2026-01-01")):
            raise ValueError("CA_DATED_ANNUAL_ORIGINAL_COMMON_AMOUNT_DATES_REQUIRED")
        typed=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
        return dict(issuer=subject.group("issuer"),ticker=subject.group("ticker"),listing=bound["source_listing_identity"],amount=float(amount),
            record=str(record.date()),pay=str(pay.date()),publication=str(pub.date()),available=None,currency_basis="INFERRED_USD_CONTEXT",
            body_ref=copy.deepcopy(item["fragment_ref"]),header_ref=copy.deepcopy(headers[0]["fragment_ref"]),source_paragraph=text,
            source_original_typed_text_digest=typed,source_original_typed_text_digest_recipe="UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT",
            source_declared_ex_date=None,source_declared_ex_date_role="NONOPERATIVE_ISSUER_EX_OBSERVATION_RETAINED_DEFAULT_RESEARCH_CLOCK",
            issuer_observed_ex_date=str(observed.date()),issuer_observed_ex_source_ref=copy.deepcopy(item["fragment_ref"]),source_disagreement_preserved=True,
            source_US_context_literal=bound["source_US_context_literal"],original_source_unit_literal="per "+subject.group("ticker")+" share",
            source_subject_role="ORIGINAL_FIXED_ANNUAL_SINGLE_MONETARY_COMMON_PAYMENT_WITH_SEPARATE_SEC_IDENTITY_UNIT_AND_CASH_POLICY",
            source_registrant_name_literal=bound["source_legal_issuer_literal"],source_common_cover_class_literal="Common Stock",
            source_cash_classification_literal="annual",annualized_rate_conversion=False,annual_fixed_single_payment=True,
            cash_word_literal_in_press_announcement=False,source_cash_medium_role="SEC_MONETARY_DIVIDENDS_PAYABLE_PER_SHARE_AND_COMMON_CASH_POLICY_RESEARCH",
            source_full_HTTP_sha256=None,source_full_HTTP_bytes=None,full_HTTP_body_locally_available=False,
            original_article_fragment_ref=copy.deepcopy(source["original_article_fragment_ref"]),current_transport_capture_utc=str(capture.tz_convert("UTC")),
            capture_is_not_available_at=True,historical_availability_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
            actual_SEC_HTTP_or_header_authority=False,source_fragment_physical_sha256=item["fragment_ref"]["sha256"],source_text_utf8_sha256=item["visible_text_utf8_sha256"])

    if sec_parent_exhibit_fact is not None:
        if same_file_identity_source is not None:
            raise ValueError("CA_SEC_PARENT_EXHIBIT_MUST_REMAIN_DISTINCT_FROM_SAME_BODY_IDENTITY")
        return _sec_parent_exhibit_common_cash_terms(sec_parent_exhibit_fact,source=source,pinned=pinned,projection=projection,pub=pub,capture=capture,header_ref=headers[0]["fragment_ref"],locator_ref=sec_parent_exhibit_locator_ref)
    pattern=r"\b(?P<action>declared|approved|increased|raised)(?: on (?P<board_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}))? (?:a |an |its |the )?(?P<classification>regular(?: quarterly)?|quarterly)(?: cash)? dividend (?:of|to) (?P<sign>US[$]|USD\s*|[$])?(?P<amount>[0-9]+(?:[.][0-9]+)?)\s*(?P<unit>cents?|dollars?)? (?P<shareunit>per common share|per share of (?:its |the company[’']s )?common stock|per share on its common stock)\b"
    # A same-sentence payment to common stockholders supplies the common class
    # even when the numeric unit precedes that beneficiary phrase.
    if separate_common_binding is not None:
        if (same_file_identity_source is not None or sec_parent_exhibit_fact is not None
                or not isinstance(separate_common_binding,dict)
                or separate_common_binding.get("status")!="PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT"
                or separate_common_binding.get("source_common_class_literal")!="Common Stock"
                or separate_common_binding.get("no_class_alias") is not True
                or separate_common_binding.get("original_frozen_class_rewritten") is not False):
            raise ValueError("CA_DATED_COMMON_SEPARATE_EXACT_COMMON_CUSIP_UNIT_REQUIRED")
        pattern=(r"(?P<action>declared) (?:a |an increase to its )(?P<classification>regular quarterly) cash dividend (?:of|to) "
            r"(?P<cents>[0-9]+(?:[.][0-9]+)?) cents \((?P<sign>[$])(?P<amount>[0-9]+(?:[.][0-9]+)?)\) "
            r"(?P<unit>)(?P<shareunit>per share)(?: from (?P<old_cents>[0-9]+(?:[.][0-9]+)?) cents "
            r"\([$](?P<old_amount>[0-9]+(?:[.][0-9]+)?)\) per share)?")
    posterior_pattern=r"On (?P<company_declaration_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}), the company (?P<action>declared) a (?P<classification>regular(?: quarterly)?|quarterly) cash dividend of (?P<sign>US[$]|USD\s*|[$])(?P<amount>[0-9]+(?:[.][0-9]+)?) (?P<shareunit>per share) to be paid on (?P<pay_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}),? to all (?P<common_beneficiaries>common stockholders) of record as of (?P<record_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})[.]"
    # A distribution uses the same common-cash lifecycle. Its amount, class and
    # payment dates must remain one explicit consecutive declaration; no annual
    # rate conversion, class substitution or cross-paragraph date completion.
    distribution_pattern=r"(?P<action>declared) (?:a|its) (?P<classification>quarterly) cash distribution of (?P<sign>US[$]|USD\s*|[$])(?P<amount>[0-9]+(?:[.][0-9]+)?) (?P<shareunit>per share on shares of the Company[’']s common stock)[.] The distribution is payable on (?P<pay_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}) to the stockholders of record at the close of business on (?P<record_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})[.]"
    selected=[]
    for item in source.get("cash_fragments",[]):
        text=projection(item)
        for m in re.finditer(pattern,text,re.I):selected.append((item,text,m,False,False))
        posterior=re.fullmatch(posterior_pattern,text,re.I)
        if posterior is not None:selected.append((item,text,posterior,True,False))
        for distribution in re.finditer(distribution_pattern,text,re.I):
            selected.append((item,text,distribution,False,True))
    if len(selected)!=1:raise ValueError("CA_DATED_COMMON_UNIQUE_DECLARED_COMMON_CASH_REQUIRED")
    item,text,m,posterior_common,distribution_common=selected[0]
    issuer=None;listing=None;subject_literal=None;us_text=None;source_subject_role=None;registered=None
    if separate_common_binding is not None:
        if (posterior_common or distribution_common or Decimal(m.group("cents"))!=Decimal(m.group("amount"))*100
                or (m.group("old_cents") is not None and Decimal(m.group("old_cents"))!=Decimal(m.group("old_amount"))*100)):
            raise ValueError("CA_DATED_COMMON_SEPARATE_CENTS_DOLLARS_CONFLICT")
    if distribution_common and same_file_identity_source is not None:
        raise ValueError("CA_DATED_COMMON_DISTRIBUTION_CANNOT_BORROW_SEC_COVER_ROLE")
    if same_file_identity_source is not None:
        supplement=same_file_identity_source
        if (supplement.get("schema_version")!="B_HISTORICAL_SAME_FILE_ISSUER_IDENTITY_SUPPLEMENT_V1"
                or supplement.get("original_cash_custody_ref")!=source_custody_ref
                or supplement.get("source_url")!=source["source_url"] or supplement.get("http_status")!=200
                or supplement.get("received_http_bytes_sha256")!=source["received_http_bytes_sha256"]
                or supplement.get("received_bytes")!=source["received_bytes"]
                or supplement.get("same_exact_original_http_body_sha256") is not True
                or supplement.get("historical_availability_status")!="UNKNOWN"
                or supplement.get("source_sec_same_file_submission_header_claim") is not False
                or any(supplement.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
            raise ValueError("CA_DATED_COMMON_SAME_BODY_IDENTITY_CUSTODY_REQUIRED")
        pieces={}
        for part in supplement["identity_fragments"]:
            role=part["role"]
            if role in pieces:raise ValueError("CA_DATED_COMMON_UNIQUE_SAME_FILE_CLASS_REQUIRED")
            pieces[role]=projection(part)
        if set(pieces)!={"SAME_FILE_REGISTRANT_NAME","SAME_FILE_US_CHARTER","SAME_FILE_COMMON_LISTING_TABLE"}:
            raise ValueError("CA_DATED_COMMON_EXACT_SAME_FILE_IDENTITY_REQUIRED")
        cover=re.fullmatch(r"Title of Each Class Trading Symbol\(s\) Name of Each Exchange on which Registered Common Stock, .+ ([A-Z][A-Z0-9.]*) (New York Stock Exchange|Nasdaq(?: Stock Market)?)",pieces["SAME_FILE_COMMON_LISTING_TABLE"])
        if (cover is None or len(re.findall(r"\bCommon Stock\b",pieces["SAME_FILE_COMMON_LISTING_TABLE"],re.I))!=1 or re.search(r"\b(?:preferred|ADS|ADR|depositary|warrant)\b",pieces["SAME_FILE_COMMON_LISTING_TABLE"],re.I)
                or not re.fullmatch(_US_CHARTER_STATE_NAMES,pieces["SAME_FILE_US_CHARTER"],re.I)):
            raise ValueError("CA_DATED_COMMON_SAME_FILE_US_COMMON_CLASS_REQUIRED")
        charter=next(part for part in supplement["identity_fragments"] if part["role"]=="SAME_FILE_US_CHARTER")
        if b'dei:EntityIncorporationStateCountryCode' not in pinned(charter["fragment_ref"]).read_bytes():
            raise ValueError("CA_DATED_COMMON_ORIGINAL_US_CHARTER_SEMANTICS_REQUIRED")
        company=re.match(r"On [A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}\s*, (.+?) \(the [“\"]Company[”\"]\) issued a press release announcing the Company[’']s Board of Directors ",text)
        if company is None or company.end()!=m.start() or not pieces["SAME_FILE_REGISTRANT_NAME"]:
            raise ValueError("CA_DATED_COMMON_EXACT_SAME_FILE_COMPANY_CASH_REQUIRED")
        registrant=next(part for part in supplement['identity_fragments'] if part['role']=='SAME_FILE_REGISTRANT_NAME')
        issuer_key=lambda value:re.sub(r'[\s.,]+','',value).casefold()
        if (not isinstance(frozen_original_issuer_literal,str) or not frozen_original_issuer_literal
                or issuer_key(company.group(1))!=issuer_key(frozen_original_issuer_literal)
                or b'dei:EntityRegistrantName' not in pinned(registrant['fragment_ref']).read_bytes()):
            raise ValueError('CA_DATED_COMMON_EXACT_FROZEN_COMPANY_SUBJECT_REQUIRED')
        issuer=company.group(1);ticker=cover.group(1);listing=("NYSE" if cover.group(2)=="New York Stock Exchange" else "NASDAQ")+":"+ticker
        registered=pieces["SAME_FILE_REGISTRANT_NAME"];us_text=pieces["SAME_FILE_US_CHARTER"]
        subject_literal=issuer;source_subject_role="SAME_FILE_COMPANY_DEFINITION_AND_UNIQUE_LISTED_COMMON_COVER_NAMES_PRESERVED"
    elif separate_common_binding is not None:
        prefix=re.fullmatch(r"[A-Z][A-Z .'-]+, [A-Z][A-Za-z.]*--\(BUSINESS WIRE\)-- (?P<issuer>.+?) \([\u201c\"].+?[\u201d\"]\) \((?P<venue>Nasdaq|NASDAQ|NYSE): (?P<ticker>[A-Z][A-Z0-9.]*)\) announced that its Board of Directors (?:today |has )?",text[:m.start()])
        issuer_key=lambda value:re.sub(r"[\s.,]+","",value).casefold()
        if (prefix is None or issuer_key(prefix.group("issuer"))!=issuer_key(separate_common_binding["source_legal_issuer_literal"])
                or prefix.group("venue").upper()+":"+prefix.group("ticker")!=separate_common_binding["source_listing_identity"]
                or issuer_key(frozen_original_issuer_literal or "")!=issuer_key(prefix.group("issuer"))):
            raise ValueError("CA_DATED_COMMON_SEPARATE_LISTED_ISSUER_CASH_SUBJECT_REQUIRED")
        issuer=prefix.group("issuer");ticker=prefix.group("ticker");listing=prefix.group("venue").upper()+":"+ticker
        subject_literal=prefix.group(0);us_text=separate_common_binding["source_US_context_literal"]
        source_subject_role="SEPARATE_ORIGINAL_LISTED_REGULAR_CASH_AND_EXACT_SEC_COMMON_CUSIP_USD_SHARE_UNIT"
        registered=separate_common_binding["source_legal_issuer_literal"]
    elif distribution_common:
        contexts=source.get("same_source_identity_context_fragments",[])
        if full_body is None or len(contexts)!=1:
            raise ValueError("CA_DATED_COMMON_DISTRIBUTION_EXACT_BODY_SUBJECT_REQUIRED")
        context_item=contexts[0];context_text=projection(context_item)
        prefix=re.match(r"(?P<US_context>[A-Z][A-Z .'-]+, (?P<state>"+_US_CHARTER_STATE_NAMES+r")) (?:—|-) (?P<header_date>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}) (?:—|-) (?P<issuer>[^()]+?) \((?P<venue>NYSE|NASDAQ|NYSE_AMERICAN|CBOE):\s*(?P<ticker>[A-Z][A-Z0-9.]*)\) (?:today )?announced that its board of directors (?P<board_definition>\(the [“\"]Board[”\"]\) )?(?:has )?",context_text,re.I)
        listed=re.findall(r"\((?:NYSE|NASDAQ|NYSE_AMERICAN|CBOE):\s*[A-Z][A-Z0-9.]*\)",context_text,re.I)
        if prefix is None or len(listed)!=1 or cash._day(prefix.group('header_date'),'same_body_distribution_dateline')!=pub:
            raise ValueError("CA_DATED_COMMON_DISTRIBUTION_EXACT_DATED_LISTED_ISSUER_REQUIRED")
        if context_text==text:
            if prefix.end()!=m.start():
                raise ValueError("CA_DATED_COMMON_DISTRIBUTION_SAME_SUBJECT_ACTION_REQUIRED")
        else:
            # The explicitly defined Board can announce a separate common-cash
            # paragraph in this same body. Preserve both original ranges/texts.
            body_parser=FilingText();body_parser.feed(full_body.decode('utf-8'))
            body_text=" ".join(" ".join(body_parser.parts).split())
            if (prefix.group('board_definition') is None
                    or len(re.findall(r"\(the [“\"‘']Board[”\"’']\)",body_text,re.I))!=1
                    or len(re.findall(r"\((?:NYSE|NASDAQ|NYSE_AMERICAN|CBOE):\s*[A-Z][A-Z0-9.]*\)",body_text,re.I))!=1
                    or len(re.findall(r"announced that its board of directors\b",body_text,re.I))!=1
                    or context_item['original_byte_range'][1]>item['original_byte_range'][0]
                    or text[:m.start()]!="In addition, the Board "):
                raise ValueError("CA_DATED_COMMON_DISTRIBUTION_SAME_BODY_DEFINED_BOARD_REQUIRED")
        issuer=prefix.group('issuer');ticker=prefix.group('ticker');listing=prefix.group('venue').upper()+':'+ticker
        subject_literal=issuer+' ('+prefix.group('venue').upper()+': '+ticker+')'
        us_text=prefix.group('US_context')
        source_subject_role="SAME_BODY_DATED_LISTED_ISSUER_BOARD_AND_EXPLICIT_QUARTERLY_COMMON_CASH_DISTRIBUTION"
    elif posterior_common:
        contexts=source.get("same_source_identity_context_fragments",[])
        if full_body is None or len(contexts)!=1:
            raise ValueError("CA_DATED_COMMON_POSTERIOR_CLASS_SAME_BODY_IDENTITY_REQUIRED")
        context_text=projection(contexts[0])
        context=re.fullmatch(r"(?:(?P<US_context>[A-Z][A-Z .'-]+, (?P<state>"+_US_CHARTER_STATE_NAMES+r"|[A-Z][.]?[A-Z][.]?))--\((?:BUSINESS WIRE|GLOBE NEWSWIRE|PRNewswire|ACCESSWIRE)\)-- )?(?P<issuer>[^()]+?) \((?P<venue>NYSE|NASDAQ|NYSE_AMERICAN|CBOE):\s*(?P<ticker>[A-Z][A-Z0-9.]*)\)",context_text,re.I)
        if context is None:
            raise ValueError("CA_DATED_COMMON_EXACT_LISTED_ISSUER_REQUIRED")
        state=context.group("state")
        if state is not None and re.fullmatch(_US_CHARTER_STATE_NAMES,state,re.I) is None and state.replace(".","").upper() not in _US_STATE_POSTAL_ABBREVIATIONS.split("|"):
            raise ValueError("CA_DATED_COMMON_US_CURRENCY_CONTEXT_REQUIRED")
        issuer=context.group("issuer");ticker=context.group("ticker");listing=context.group("venue").upper()+":"+ticker
        subject_literal=context_text;us_text=context.group("US_context")
        source_subject_role="SAME_BODY_EXACT_LISTED_ISSUER_AND_COMPANY_COMMON_STOCKHOLDER_CASH_SENTENCE"
    else:
        subjects=list(re.finditer(r"([^()]+?)(?: \([A-Z][A-Z0-9]{1,9}\))? \((NYSE|NASDAQ|NYSE_AMERICAN|CBOE):\s*([A-Z][A-Z0-9.]*)\)",text[:m.start()]))
        if len(subjects)==1:
            subject=subjects[0];prefix=subject.group(1);issuer=prefix.rsplit("-- ",1)[-1].removeprefix("The Board of Directors of ")
            subject_literal=issuer+" "+subject.group(0)[len(prefix)+1:];between=text[subject.end():m.start()]
            if not re.fullmatch(r"\s*(?:yesterday |today |has |today announced that its Board of Directors (?:has )?)?",between):
                raise ValueError("CA_DATED_COMMON_DECLARATION_SUBJECT_ACTION_REQUIRED")
            ticker=subject.group(3);listing=subject.group(2)+":"+ticker
            source_subject_role="SAME_CASH_PARAGRAPH_DECLARED_COMMON_AND_EXACT_LISTED_SYMBOL"
        else:raise ValueError("CA_DATED_COMMON_EXACT_LISTED_ISSUER_REQUIRED")
    if not issuer or issuer!=" ".join(issuer.split()) or (not posterior_common and not distribution_common and subject_literal not in text):
        raise ValueError("CA_DATED_COMMON_DECLARATION_SUBJECT_ACTION_REQUIRED")
    declaration_literal=None if distribution_common or separate_common_binding is not None else m.group("company_declaration_date" if posterior_common else "board_date")
    if declaration_literal is not None and cash._day(declaration_literal,"source_company_declaration_date" if posterior_common else "private_board_declaration_date")>pub:
        raise ValueError("CA_DATED_COMMON_COMPANY_DECLARATION_AFTER_PUBLIC_HEADER" if posterior_common else "CA_DATED_COMMON_PRIVATE_BOARD_DATE_AFTER_PUBLIC_HEADER")
    sign=m.group("sign");unit=("" if posterior_common or distribution_common else m.group("unit") or "").lower();amount=Decimal(m.group("amount"))
    if unit in ("cent","cents"):
        if sign is not None:raise ValueError("CA_DATED_COMMON_AMBIGUOUS_CURRENCY_REQUIRED")
        amount/=Decimal(100)
    elif sign is None and unit not in ("dollar","dollars"):
        raise ValueError("CA_DATED_COMMON_DOLLAR_OR_CENTS_LITERAL_REQUIRED")
    explicit=sign is not None and sign.strip() in ("US$","USD")
    us=re.match(r"([A-Z][A-Z .'-]+), ("+_US_CHARTER_STATE_NAMES+"|"+_US_STATE_POSTAL_ABBREVIATIONS+"|"+"|".join(re.escape(v[0]+"."+v[1]+".") for v in _US_STATE_POSTAL_ABBREVIATIONS.split("|"))+r")(?:[.]?\s*)--\((?:BUSINESS WIRE|GLOBE NEWSWIRE|PRNewswire|ACCESSWIRE)\)--",text,re.I)
    if not explicit and us is None and us_text is None:
        # Currency context may be its own exact paragraph in the pinned body.
        # Preserve both original fragments; never concatenate source text.
        contexts=source.get("same_source_US_context_fragments",[])
        if full_body is None or len(contexts)!=1:
            raise ValueError("CA_DATED_COMMON_US_CURRENCY_CONTEXT_REQUIRED")
        context_text=projection(contexts[0])
        context=re.fullmatch(r"[A-Z][A-Z .'-]+, (?P<state>"+_US_CHARTER_STATE_NAMES+"|"+_US_STATE_POSTAL_ABBREVIATIONS+r")[.]?--\((?:BUSINESS WIRE|GLOBE NEWSWIRE|PRNewswire|ACCESSWIRE)\)--(?:[A-Z][a-z]{2}[.]? [0-9]{1,2}, 20[0-9]{2}-- Regulatory News:)?",context_text,re.I)
        if context is None:
            raise ValueError("CA_DATED_COMMON_US_CURRENCY_CONTEXT_REQUIRED")
        dateline_date=re.search(r"--([A-Z][a-z]{2}[.]? [0-9]{1,2}, 20[0-9]{2})-- Regulatory News:$",context_text,re.I)
        if dateline_date is not None and cash._day(dateline_date.group(1),"same_body_dateline_date")!=pub:
            raise ValueError("CA_DATED_COMMON_US_DATELINE_HEADER_DATE_CONFLICT")
        us_text=context_text
    if posterior_common or distribution_common:
        if not amount.is_finite() or amount<=0:raise ValueError("CA_DATED_COMMON_EXACT_RECORD_PAY_REQUIRED")
        pay_literal=m.group("pay_date");record_literal=m.group("record_date")
    else:
        dates=list(re.finditer(r"\b(?:(?:The|This)(?: quarterly)? dividend(?:s)? (?:will be|is|are) )?payable(?: on)? ([A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}),? to (?:stockholders|shareholders) of record(?: at the close of business)?(?: on| as of(?: the close of business on)?)? ([A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})[.]",text))
        if (len(dates)!=1 or dates[0].start()<m.end()
                or re.fullmatch(r"\s*(?:[.,]\s*|, a [0-9]+(?:[.][0-9]+)?% increase from \$[0-9]+(?:[.][0-9]+)? per share in the prior quarter[.]\s*)?",text[m.end():dates[0].start()]) is None
                or not amount.is_finite() or amount<=0):raise ValueError("CA_DATED_COMMON_EXACT_RECORD_PAY_REQUIRED")
        pay_literal=dates[0].group(1);record_literal=dates[0].group(2)
    pay=cash._day(pay_literal,"pay_date",known_future_schedule=True);record=cash._day(record_literal,"record_date")
    if not pub<=record<=pay or record>=pd.Timestamp("2026-01-01"):raise ValueError("CA_DATED_COMMON_SOURCE_DATE_ORDER_REQUIRED")
    typed=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
    return dict(issuer=issuer,ticker=ticker,listing=listing,amount=float(amount),
        source_amount_literal=m.group("amount"),source_amount_unit_literal=unit or sign,
        currency_basis="EXPLICIT_USD" if explicit else "INFERRED_USD_CONTEXT",source_currency_explicit_USD=explicit,
        record=str(record.date()),pay=str(pay.date()),publication=str(pub.date()),available=None,
        body_ref=copy.deepcopy(item["fragment_ref"]),header_ref=copy.deepcopy(headers[0]["fragment_ref"]),source_paragraph=text,
        source_original_typed_text_digest=typed,source_original_typed_text_digest_recipe="UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT",
        source_declared_ex_date=None,source_US_context_literal=us_text if us is None else us.group(0),source_issuer_listing_literal=subject_literal,
        original_source_unit_literal=m.group("shareunit"),source_subject_role=source_subject_role,source_registrant_name_literal=registered,source_common_cover_class_literal="Common Stock" if separate_common_binding is not None else None if same_file_identity_source is None else "Common Stock",exact_registered_name_equivalence_granted=False,
        source_cash_classification_literal=m.group("classification"),source_common_beneficiary_literal=None if not posterior_common else m.group("common_beneficiaries"),private_board_declaration_date=None if posterior_common or declaration_literal is None else str(pd.Timestamp(declaration_literal).date()),source_company_declaration_date=None if not posterior_common else str(pd.Timestamp(declaration_literal).date()),source_full_HTTP_sha256=source["received_http_bytes_sha256"],
        source_full_HTTP_bytes=source["received_bytes"],full_HTTP_body_locally_available=full_body is not None,
        current_transport_capture_utc=str(capture.tz_convert("UTC")),capture_is_not_available_at=True,
        historical_availability_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",actual_SEC_HTTP_or_header_authority=False,
        source_fragment_physical_sha256=item["fragment_ref"]["sha256"],source_text_utf8_sha256=item["visible_text_utf8_sha256"])

def _frozen_common_cash_namespace(payload,entry,*,source_ref_transport=()):
    """Reuse the accepted raw COM coordinate, preserving source legal-name spelling."""
    if (payload.get("frozen_common_namespace_role")!=FROZEN_COMMON_NAMESPACE_ROLE
            or payload.get("frozen_account_identity_ref") is None
            or payload.get("historical_available_at") is not None
            or any(payload.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
        raise ValueError("CA_EXPLICIT_FROZEN_COMMON_NAMESPACE_REQUIRED")
    t=cash._terms(payload)
    if t["security_type"]!="COMMON_STOCK":
        raise ValueError("CA_FROZEN_NAMESPACE_COMMON_SHARE_REQUIRED")
    refs=payload["source_context_refs"]
    def pinned(ref):
        if sum(ref==r for r in refs)!=1:raise ValueError("CA_FROZEN_NAMESPACE_EXACT_SOURCE_PIN_REQUIRED")
        target=next((tx["custody_ref"] for tx in source_ref_transport if tx["original_ref"]==ref),ref)
        return _pin(target)
    context=payload["source_identity_context"];raw_ref=payload["raw_source_ref"]
    separate_common_binding=None
    fixed_annual_common_binding=None
    same_file=context.get("role")=="SAME_ORIGINAL_ISSUER_FILING_COMMON_COVER_AND_CASH_CLAUSE"
    dated_cents=context.get("role")=="SAME_ORIGINAL_DATED_COMMON_STOCK_CENTS_DECLARATION"
    dated_common=context.get("role")==DATED_COMMON_DECLARATION_ROLE
    sec_linked=context.get("role")==SEC_PARENT_EXHIBIT_COMMON_ROLE
    if (context.get("role") not in ("SAME_ORIGINAL_DECLARATION_US_COMMON_SHARE_AND_LISTED_SYMBOL",
                                   "SAME_ORIGINAL_ISSUER_FILING_COMMON_COVER_AND_CASH_CLAUSE",
                                   "SAME_ORIGINAL_DATED_COMMON_STOCK_CENTS_DECLARATION",DATED_COMMON_DECLARATION_ROLE,SEC_PARENT_EXHIBIT_COMMON_ROLE)
            or context.get("original_cash_projection_ref")!=raw_ref
            or context.get("issuer_literal")!=t["issuer"]
            or re.sub(r"\s+","",context.get("listing_literal","")).upper()!=t["listing"]
            or (not (dated_cents or dated_common or sec_linked) and (payload.get("source_original_cash_unit_literal")!="PER_COMMON_SHARE"
                or not re.search(r"\b(?:per\s+common\s+share|common\s+share\s+dividend)\b",context.get("common_unit_context_literal",""),re.I)))
            or (dated_cents and payload.get("source_original_cash_unit_literal")!="cents per share")
            or context.get("historical_availability_authority")!="UNKNOWN"):
        raise ValueError("CA_FROZEN_NAMESPACE_SOURCE_SUBJECT_REQUIRED")
    from scripts.storage.refresh_sec_event_originals import FilingText
    with pinned(raw_ref).open("rb") as stream:raw=stream.read()
    parser=FilingText();parser.feed(raw.decode("utf-8"))
    normalized=lambda x:" ".join(x.split())
    literal=payload["source_paragraph"];visible=normalized(("" if same_file else " ").join(parser.parts))
    recipe=payload.get("source_original_typed_text_digest_recipe")
    if recipe!="UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT":
        raise ValueError("CA_FROZEN_NAMESPACE_ORIGINAL_DIGEST_RECIPE_REQUIRED")
    digest=hashlib.sha256(json.dumps(literal,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
    if (visible!=normalized(literal) or digest!=payload.get("source_original_typed_text_digest")
            or (raw_ref.get("bytes") is not None and len(raw)!=raw_ref["bytes"])
            or not normalized(context.get("common_unit_context_literal",""))
            or normalized(context["common_unit_context_literal"]) not in visible
            or (not (same_file or dated_common or sec_linked) and (context["issuer_literal"] not in visible or context["listing_literal"] not in visible))):
        raise ValueError("CA_FROZEN_NAMESPACE_ORIGINAL_SOURCE_LITERAL_REQUIRED")
    same_file_proof=None
    if same_file:
        # Issuer self-distribution is its own source role, never a SEC HTTP/header.
        from decimal import Decimal
        source_ref=context["cash_source_custody_ref"];cover_ref=context["same_file_identity_custody_ref"]
        source=json.loads(pinned(source_ref).read_text(encoding="utf-8"))
        cover=json.loads(pinned(cover_ref).read_text(encoding="utf-8"))
        http_ref=source["original_HTTP_ref"];http=pinned(http_ref)
        transport_ref=source["original_capture_ref"];transport=json.loads(pinned(transport_ref).read_text(encoding="utf-8"))
        locator_ref=source["original_issuer_feed_locator_custody_ref"];locator=json.loads(pinned(locator_ref).read_text(encoding="utf-8"))
        meta_ref=locator["original_metadata_ref"];metadata=json.loads(pinned(meta_ref).read_text(encoding="utf-8"))
        flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
        if (source.get("schema")!="ISSUER_ORIGINAL_ORDINARY_CASH_FRAGMENT_CUSTODY_V1"
                or cover.get("schema")!="ISSUER_SELF_DISTRIBUTED_8K_SAME_FILE_COMMON_COVER_CUSTODY_V1"
                or transport.get("schema")!="ISSUER_SELF_DISTRIBUTED_HISTORICAL_8K_ORIGINAL_HTTP_TRANSPORT_V1"
                or transport.get("transport_role")!="INDEPENDENT_ISSUER_SELF_DISTRIBUTION_CDN_NOT_SEC_HTTP"
                or locator.get("schema")!="ISSUER_SERVER_YEAR_FILTERED_SEC_SELF_DISTRIBUTION_LOCATOR_CUSTODY_V1"
                or any(o.get(k) is not False for o in (source,cover,transport,locator) for k in flags)
                or any(o.get("historical_availability_authority")!="UNKNOWN" for o in (source,cover,transport,locator))
                or source.get("source_publication_date_role")!="REAL_ISSUER_YEAR_FILTERED_FILING_FEED_DATE_NOT_PRIVATE_BOARD_DAY_NOT_SEC_HTTP"
                or source.get("source_declared_ex_date") is not None
                or source.get("same_source_identity_projection_ref")!=cover_ref
                or any(o.get("original_HTTP_ref")!=http_ref for o in (cover,transport))
                or transport.get("actual_status")!=200 or locator.get("actual_status")!=200
                or transport.get("body_sha256")!=http_ref["sha256"]
                or transport.get("original_bytes")!=http.stat().st_size
                or source.get("original_HTTP_sha256")!=http_ref["sha256"]
                or source.get("original_HTTP_bytes")!=http.stat().st_size
                or transport.get("original_issuer_feed_locator_custody_ref")!=locator_ref
                or cover.get("original_transport_ref")!=transport_ref
                or source.get("source_url")!=payload["source_url"] or transport.get("requested_url")!=payload["source_url"]
                or source.get("ticker")!=t["ticker"] or cover.get("ticker_literal")!=t["ticker"]
                or source.get("legal_name_literal")!=t["issuer"] or cover.get("legal_name_literal")!=t["issuer"]
                or type(source.get("cik")) is not int or source["cik"]!=cover.get("cik")
                or int(locator["CIK"])!=source["cik"]):
            raise ValueError("CA_FROZEN_NAMESPACE_SAME_FILE_ISSUER_CUSTODY_REQUIRED")
        def range_text(ref,rng,text_ref):
            if not (isinstance(rng,list) and len(rng)==2 and all(type(n) is int for n in rng)
                    and 0<=rng[0]<rng[1]<=http.stat().st_size and rng[1]-rng[0]<=65536):
                raise ValueError("CA_FROZEN_NAMESPACE_BOUNDED_ORIGINAL_RANGE_REQUIRED")
            with http.open("rb") as stream:stream.seek(rng[0]);part=stream.read(rng[1]-rng[0])
            if part!=pinned(ref).read_bytes():raise ValueError("CA_FROZEN_NAMESPACE_SAME_BODY_RANGE_CHANGED")
            parsed=FilingText();parsed.feed(part.decode("utf-8"));shown=normalized("".join(parsed.parts))
            if pinned(text_ref).read_text(encoding="utf-8").removesuffix("\n")!=shown:
                raise ValueError("CA_FROZEN_NAMESPACE_SAME_BODY_VISIBLE_TEXT_CHANGED")
            return shown
        cash_text=range_text(raw_ref,source["source_original_byte_range"],source["text_projection_ref"])
        cover_text=range_text(cover["cover_original_fragment_ref"],cover["cover_original_byte_range"],cover["cover_visible_text_ref"])
        name_text=range_text(cover["registrant_name_original_fragment_ref"],cover["registrant_name_original_byte_range"],cover["registrant_name_visible_text_ref"])
        typed=lambda v:hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
        if (cash_text!=visible or source.get("dividend_paragraph")!=literal
                or source.get("original_cash_fragment_ref")!=raw_ref
                or source.get("dividend_paragraph_typed_content_recipe")!=recipe
                or source.get("dividend_paragraph_typed_content_sha256")!=digest
                or cover_text!=cover.get("complete_cover_row_literal")
                or typed(cover_text)!=cover.get("cover_visible_typed_content_sha256")
                or typed(name_text)!=cover.get("registrant_name_visible_typed_content_sha256")
                or name_text!=t["issuer"] or cover.get("exchange_literal")!="New York Stock Exchange"
                or not re.fullmatch(r"Common Stock, .+ "+re.escape(t["ticker"])+r" New York Stock Exchange",cover_text)
                or re.search(r"\b(?:preferred|ADS|ADR|depositary)\b",cover_text,re.I)):
            raise ValueError("CA_FROZEN_NAMESPACE_SAME_FILE_COMMON_NAME_REQUIRED")
        us_ref=context["same_file_US_context_custody_ref"];us=json.loads(pinned(us_ref).read_text(encoding="utf-8"))
        us_text=range_text(us["original_fragment_ref"],us["original_byte_range"],us["visible_text_ref"])
        charter=re.match(r"("+_US_CHARTER_STATE_NAMES+r") [0-9 -]+ \(State or other jurisdiction of incorporation\)",us_text)
        if (us.get("schema")!="ISSUER_SELF_DISTRIBUTED_8K_US_JURISDICTION_CONTEXT_CUSTODY_V1"
                or us.get("original_HTTP_ref")!=http_ref or us.get("cash_source_custody_ref")!=source_ref
                or us.get("same_file_identity_custody_ref")!=cover_ref
                or us.get("historical_availability_authority")!="UNKNOWN" or any(us.get(k) is not False for k in flags)
                or us.get("visible_text_literal")!=us_text or typed(us_text)!=us.get("visible_text_typed_content_sha256")
                or us.get("visible_text_typed_content_recipe")!=recipe or charter is None
                or "(Address of principal executive offices)" not in us_text
                or not re.search(r"\b"+re.escape(charter.group(1))+r" [0-9]{5}\b",us_text)
                or source.get("currency_literal")!="$" or payload.get("currency")!="USD"
                or t["currency_basis"]!="INFERRED_USD_CONTEXT"
                or us.get("currency_role")!="DOLLAR_COMMON_CASH_US_ISSUER_CONTEXT_INFERRED_NOT_EXPLICIT_USD"
                or context.get("original_common_cover_literal")!=cover_text
                or context.get("US_context_literal")!=us_text):
            raise ValueError("CA_FROZEN_NAMESPACE_SAME_FILE_US_COMMON_DOLLAR_CONTEXT_REQUIRED")
        rows=metadata.get("GetEdgarFilingListResult",[])
        if not rows or any(not (str(pd.Timestamp(r["FilingDate"]).year)==str(locator["year"])
                                and pd.Timestamp(r["FilingDate"])<pd.Timestamp("2026-01-01")
                                and r.get("FilingTypeMnemonic")=="8-K") for r in rows):
            raise ValueError("CA_FROZEN_NAMESPACE_PRE2026_ISSUER_FILING_FEED_REQUIRED")
        selected=[r for r in rows if any(d.get("DocumentType")=="HTML" and d.get("Url")==payload["source_url"] for d in r["DocumentList"])]
        pub=cash._day(t["publication"],"issuer_feed_filing_date")
        capture=pd.Timestamp(transport["request_end_utc"]);start=pd.Timestamp(transport["request_start_utc"])
        if (len(selected)!=1 or not locator.get("selected_rows")
                or any(set(r)!={"DocumentList","FilingDate","FilingId","FilingTypeMnemonic","LinkToDetailPage"} for r in locator["selected_rows"])
                or {k:selected[0][k] for k in ("DocumentList","FilingDate","FilingId","FilingTypeMnemonic","LinkToDetailPage")} not in locator["selected_rows"]
                or pd.Timestamp(selected[0]["FilingDate"])!=pub
                or any(o.get(k)!=str(pub.date()) for o,k in ((source,"source_publication_date"),(source,"actual_filed_date"),(cover,"source_publication_calendar_date")))
                or pd.isna(capture) or capture.tzinfo is None or pd.isna(start) or start.tzinfo is None
                or start>capture or capture<pub.tz_localize("UTC")):
            raise ValueError("CA_FROZEN_NAMESPACE_TRUE_ISSUER_FEED_DATE_REQUIRED")
        statement=r"declared [^.]*?quarterly common share dividend in the amount of [A-Za-z -]+ \([$]([0-9]+[.][0-9]+)\) per share, payable on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), to shareholders of record(?: at the close of business)? on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})[.]"
        matches=list(re.finditer(statement,visible));day=re.match(r"On ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), ",visible)
        if (len(matches)!=1 or day is None or Decimal(matches[0].group(1))!=Decimal(str(t["amount"]))
                or str(pd.Timestamp(matches[0].group(2)).date())!=t["pay"]
                or str(pd.Timestamp(matches[0].group(3)).date())!=t["record"]
                or Decimal(source["source_cash_amount_decimal"])!=Decimal(str(t["amount"]))
                or source.get("source_record_date")!=t["record"] or source.get("source_pay_date")!=t["pay"]
                or source.get("source_raw_share_unit")!="PER_COMMON_SHARE"
                or source.get("source_cash_classification")!="QUARTERLY_COMMON_SHARE_CASH_DIVIDEND"
                or str(pd.Timestamp(day.group(1)).date())!=source.get("private_board_declaration_date")
                or pd.Timestamp(day.group(1))>pub):
            raise ValueError("CA_FROZEN_NAMESPACE_EXACT_CURRENT_COMMON_CASH_TERMS_REQUIRED")
        same_file_proof=dict(source_identity_context_role=context["role"],same_file_identity_custody_ref=cover_ref,
            cash_source_custody_ref=source_ref,original_HTTP_ref=http_ref,issuer_filing_feed_ref=meta_ref,
            issuer_feed_locator_ref=locator_ref,original_transport_ref=transport_ref,
            source_publication_date=str(pub.date()),source_publication_date_role=source["source_publication_date_role"],
            private_board_declaration_date=source["private_board_declaration_date"],
            cik=source["cik"],cik_role="ISSUER_FEED_AND_DOCUMENT_URL_NOT_SAME_FILE_SEC_HEADER",
            actual_SEC_HTTP_or_header_authority=False,source_common_cover_literal=cover_text,
            current_transport_capture_utc=str(capture.tz_convert("UTC")),capture_is_not_available_at=True,
            original_text_projection_role="EXISTING_FILINGTEXT_JOIN_PARTS_THEN_WHITESPACE_COLLAPSE",
            source_registrant_name_literal=name_text,source_declared_ex_date=None,
            same_file_US_context_custody_ref=us_ref,source_US_charter_state=charter.group(1),
            source_currency_role=us["currency_role"],source_currency_explicit_USD=False)

    if dated_cents:
        # A dated common-stock cents clause uses its own original article/header role.
        from decimal import Decimal
        source_ref=context["cash_source_custody_ref"];source=json.loads(pinned(source_ref).read_text(encoding="utf-8"))
        http_ref=source["original_HTTP_ref"];http=pinned(http_ref)
        transport_ref=source["HTTP_transport_ref"];transport=json.loads(pinned(transport_ref).read_text(encoding="utf-8"))
        locator_ref=source["original_issuer_year_locator_custody_ref"];locator=json.loads(pinned(locator_ref).read_text(encoding="utf-8"))
        metadata_ref=locator["raw_metadata_ref"];metadata=json.loads(pinned(metadata_ref).read_text(encoding="utf-8"))
        flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
        if (source.get("schema")!="ISSUER_ORIGINAL_ORDINARY_CASH_FRAGMENT_CUSTODY_V1"
                or source.get("source_role")!="ISSUER_HOSTED_ORIGINAL_ORDINARY_COMMON_CASH_DECLARATION"
                or transport.get("schema")!="ISSUER_FIXED_HISTORICAL_ORIGINAL_HTTP_TRANSPORT_V1"
                or locator.get("schema")!="ISSUER_FIXED_YEAR_FILTERED_PRESS_RELEASE_LOCATOR_CUSTODY_V1"
                or any(o.get(k) is not False for o in (source,transport,locator) for k in flags)
                or any(o.get("historical_availability_authority")!="UNKNOWN" for o in (source,transport,locator))
                or source.get("cash_available_at") is not None or source.get("source_direct_ex_date") is not None
                or source.get("private_board_announcement_date") is not None
                or source.get("source_ex_date_authority")!="UNKNOWN_NOT_ANNOUNCED_IN_SELECTED_ORIGINAL_CASH_PARAGRAPH"
                or source.get("source_publication_role")!="ABSOLUTE_ORIGINAL_ARTICLE_HEADER_DATE_NOT_PRIVATE_BOARD_DAY"
                or source.get("source_unit")!="PER_COMMON_SHARE" or source.get("source_classification")!="QUARTERLY_COMMON_STOCK_CASH"
                or source.get("source_issuer_literal")!=t["issuer"] or source.get("source_listing_literal")!=t["listing"]
                or source.get("source_url")!=payload["source_url"] or transport.get("requested_url")!=payload["source_url"]
                or transport.get("actual_status")!=200 or transport.get("original_HTTP_ref")!=http_ref
                or any(o.get("original_HTTP_sha256")!=http_ref["sha256"] or o.get("original_bytes")!=http.stat().st_size for o in (source,transport))):
            raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_ORIGINAL_CUSTODY_REQUIRED")
        typed=lambda v:hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
        def projection(item):
            rng=item["raw_byte_range"]
            if not (isinstance(rng,list) and len(rng)==2 and all(type(n) is int for n in rng)
                    and 0<=rng[0]<rng[1]<=http.stat().st_size and rng[1]-rng[0]<=16384):
                raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_BOUNDED_RANGE_REQUIRED")
            with http.open("rb") as stream:stream.seek(rng[0]);part=stream.read(rng[1]-rng[0])
            if part!=pinned(item["raw_fragment_ref"]).read_bytes():
                raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_SAME_BODY_REQUIRED")
            parsed=FilingText();parsed.feed(part.decode("utf-8"));shown=normalized(" ".join(parsed.parts))
            saved=pinned(item["visible_text_ref"]).read_bytes().decode("utf-8")
            if (saved not in (shown,shown+"\n") or shown!=item["visible_literal"]
                    or item.get("visible_literal_content_recipe")!=recipe
                    or typed(shown)!=item.get("visible_literal_typed_content_sha256")):
                raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_ORIGINAL_TEXT_REQUIRED")
            return shown
        cash_text=projection(source["cash_projection"]);date_text=projection(source["date_projection"])
        us_text=projection(source["same_source_US_context_projection"])
        subject_literal=source.get("same_source_issuer_listing_literal")
        subject=re.fullmatch(r"(.+?) \((NYSE|NASDAQ|NYSE_AMERICAN|CBOE):\s*([A-Z][A-Z0-9.]*)\)",subject_literal) if isinstance(subject_literal,str) else None
        if (source["cash_projection"]["raw_fragment_ref"]!=raw_ref or cash_text!=literal
                or subject is None or subject_literal!=normalized(subject_literal) or subject_literal not in cash_text
                or subject.group(1)!=t["issuer"] or subject.group(2)+":"+subject.group(3)!=t["listing"]
                or source.get("same_source_common_class_evidence")!="EXPLICIT_QUARTERLY_DIVIDEND_ON_COMMON_STOCK_IN_SAME_CASH_PARAGRAPH"
                or not re.search(r"\bis (?:a|an) (?:[A-Za-z-]+ )?U[.]S[.] (?:[A-Za-z-]+ ){0,8}(?:company|corporation)\b",us_text)
                or not re.search(r"\bCompany headquarters are located in\b",us_text)
                or source.get("source_currency_literal")!="cents" or source.get("source_currency_explicit_USD") is not False
                or source.get("source_currency_role")!="CENTS_COMMON_CASH_SAME_SOURCE_US_ISSUER_CONTEXT_INFERRED_NOT_EXPLICIT_USD"
                or source.get("source_currency")!="USD_CONTEXT_INFERENCE_ONLY"
                or payload.get("currency")!="USD" or t["currency_basis"]!="INFERRED_USD_CONTEXT"):
            raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_COMMON_US_UNIT_REQUIRED")
        pub=cash._day(t["publication"],"original_article_header_date")
        start=pd.Timestamp(transport["request_start_UTC"]);capture=pd.Timestamp(transport["request_end_UTC"])
        rows=metadata.get("GetPressReleaseListResult",[])
        if (not rows or locator.get("bodyType")!=0 or locator.get("year_filter_server_side") is not True
                or any(r.get("Body") not in (None,"") or r.get("ShortBody") not in (None,"")
                       or pd.Timestamp(r["PressReleaseDate"]).year!=locator["year"]
                       or pd.Timestamp(r["PressReleaseDate"])>=pd.Timestamp("2026-01-01") for r in rows)):
            raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_PRE2026_METADATA_REQUIRED")
        from urllib.parse import urljoin
        selected=[r for r in rows if urljoin(payload["source_url"],r.get("LinkToDetailPage",""))==payload["source_url"]]
        expected=None if len(selected)!=1 else dict(publication_date=str(pd.Timestamp(selected[0]["PressReleaseDate"]).date()),raw_publication_datetime_unzoned=selected[0]["PressReleaseDate"],headline=selected[0]["Headline"],url=urljoin(payload["source_url"],selected[0]["LinkToDetailPage"]),press_release_id=selected[0]["PressReleaseId"])
        if (expected is None or expected not in locator.get("selected_rows",[])
                or expected["publication_date"]!=str(pub.date())
                or source.get("raw_feed_datetime_without_timezone")!=expected["raw_publication_datetime_unzoned"]
                or source.get("source_publication_date")!=str(pub.date()) or source.get("announcement_date")!=str(pub.date())
                or not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}",date_text) or pd.Timestamp(date_text)!=pub
                or pd.isna(start) or start.tzinfo is None or pd.isna(capture) or capture.tzinfo is None
                or start>capture or capture<pub.tz_localize("UTC")):
            raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_TRUE_HEADER_DATE_REQUIRED")
        statement=re.escape(subject_literal)+r" today (?:raised the quarterly dividend on (?:the company.{1,8}s|its) common stock from ([0-9.]+) cents per share to |declared a quarterly dividend on (?:the company.{1,8}s|its) common stock of )([0-9.]+) cents per share"
        matches=list(re.finditer(statement,cash_text));dates=re.findall(r"The dividends are payable ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4}), to shareholders of record on ([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})[.]",cash_text)
        if (len(matches)!=1 or len(dates)!=1 or Decimal(matches[0].group(2))/Decimal(100)!=Decimal(str(t["amount"]))
                or matches[0].group(2)!=source.get("source_cash_amount_literal_cents")
                or Decimal(source["source_cash_amount_decimal"])!=Decimal(str(t["amount"]))
                or str(pd.Timestamp(dates[0][0]).date())!=t["pay"] or str(pd.Timestamp(dates[0][1]).date())!=t["record"]
                or source.get("source_record_date")!=t["record"] or source.get("source_pay_date")!=t["pay"]):
            raise ValueError("CA_FROZEN_NAMESPACE_DATED_CENTS_EXACT_CURRENT_QUARTER_TERMS_REQUIRED")
        same_file_proof=dict(source_identity_context_role=context["role"],cash_source_custody_ref=source_ref,
            original_HTTP_ref=http_ref,original_transport_ref=transport_ref,issuer_year_metadata_ref=metadata_ref,
            issuer_year_locator_ref=locator_ref,original_date_projection=source["date_projection"],
            original_cash_projection=source["cash_projection"],original_US_context_projection=source["same_source_US_context_projection"],
            source_publication_date=str(pub.date()),source_publication_date_role=source["source_publication_role"],
            private_board_declaration_date=None,source_declared_ex_date=None,actual_SEC_HTTP_or_header_authority=False,
            current_transport_capture_utc=str(capture.tz_convert("UTC")),capture_is_not_available_at=True,
            source_current_quarterly_cents=matches[0].group(2),source_original_previous_rate_cents=matches[0].group(1),
            annual_rate_is_not_current_quarterly_cash=True,source_currency_role=source["source_currency_role"],source_currency_explicit_USD=False)

    if dated_common or sec_linked:
        source_ref=context["cash_source_custody_ref"];source=json.loads(pinned(source_ref).read_text(encoding="utf-8"))
        supplement_ref=context.get("same_file_identity_supplement_ref")
        supplement=None if supplement_ref is None else json.loads(pinned(supplement_ref).read_text(encoding="utf-8"))
        linked_fact=None
        if sec_linked:
            addendum=json.loads(pinned(context["sec_parent_exhibit_addendum_ref"]).read_text(encoding="utf-8"))
            matches=[f for f in addendum.get("facts",[]) if f.get("original_candidate_unsupported_key") in entry["original_unsupported_keys"]]
            if (addendum.get("schema")!="B_EXISTING_PM_SEP_BLOCKED_COMMON_UNIT_HISTORICAL_SOURCE_ADDENDUM_V1" or len(matches)!=1
                    or context.get("source_paragraph_terms_role")!="ORIGINAL_PARENT_COMMON_AMOUNT_ONLY_NOT_COMPLETE_RECORD_PAY_CLAUSE"
                    or context.get("complete_terms_same_original_paragraph") is not False
                    or entry["original_unsupported_keys"]!=[matches[0]["original_candidate_unsupported_key"]]):
                raise ValueError("CA_SEC_PARENT_EXHIBIT_EXACT_ORIGINAL_KEY_AND_SEPARATE_TERMS_ROLE_REQUIRED")
            linked_fact=matches[0]
        annual_ref=context.get("fixed_annual_common_cash_support_ref")
        if annual_ref is not None:
            from decimal import Decimal
            import xml.etree.ElementTree as ET
            annual_support=json.loads(pinned(annual_ref).read_text(encoding="utf-8"));flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
            if (not dated_common or sec_linked or supplement is not None
                    or annual_support.get("schema")!="B_SEPARATE_ORIGINAL_FIXED_ANNUAL_COMMON_MONETARY_DIVIDEND_SUPPORT_V1"
                    or annual_support.get("source_role")!="ISSUER_ORIGINAL_ANNUAL_SINGLE_PAYMENT_WITH_PRE2026_SEC_COMMON_CUSIP_USD_PER_SHARE_AND_CASH_POLICY_SUPPORT"
                    or any(annual_support.get(k) is not False for k in flags)
                    or annual_support.get("same_file_cash_claim") is not False or annual_support.get("cash_word_literal_in_press_announcement") is not False
                    or annual_support.get("annual_amount_is_fixed_single_payment") is not True or annual_support.get("annualized_rate_conversion") is not False
                    or annual_support.get("share_quantity_effect") is not False or annual_support.get("no_class_alias") is not True
                    or annual_support.get("original_frozen_class_rewritten") is not False or annual_support.get("available_at") is not None
                    or annual_support.get("historical_availability_authority")!="UNKNOWN" or annual_support.get("actual_exchange_ex_authority")!="UNKNOWN"
                    or annual_support.get("independent_actual_ex_date") is not None or annual_support.get("source_disagreement_preserved") is not True
                    or annual_support.get("research_ex_date_policy")!="ORIGINAL_DEFAULT_NORMAL_CASH_TPLUS1_RECORD_CALENDAR"):
                raise ValueError("CA_FROZEN_NAMESPACE_FIXED_ANNUAL_MONETARY_SCOPE_REQUIRED")
            frozen=json.loads(pinned(payload["frozen_account_identity_ref"]).read_text(encoding="utf-8"));prior=cash._day(entry["prior_raw_close"]["prior_date"],"annual_prior_identity")
            rows=[x["original_source_row"] for x in frozen["rows"] if cash._day(x["original_source_row"]["effective_start"],"annual_start")<=prior<=cash._day(x["original_source_row"]["effective_end"],"annual_end")]
            if len(rows)!=1:raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_ONE_ORIGINAL_IDENTITY_REQUIRED")
            row=rows[0];legal=annual_support["legal_issuer_literal"];cik=annual_support["issuer_CIK"];key=lambda v:re.sub(r"[\s.,]+","",v).casefold()
            if (type(cik) is not int or cik<=0 or annual_support.get("original_frozen_issuer_literal")!=row["issuer_name"]
                    or annual_support.get("original_frozen_class_literal")!=row["title_of_class"] or row["title_of_class"]!="Common Stock"
                    or row["security_id_type"]!="CUSIP" or row["security_id"]!=row["cusip"] or row["mapping_status"]!="RESOLVED"):
                raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_ORIGINAL_COMMON_CUSIP_REQUIRED")
            def original_part(body,item):
                span=item["original_byte_range"]
                if (not isinstance(span,list) or len(span)!=2 or any(type(n) is not int for n in span)
                        or not 0<=span[0]<span[1]<=body.stat().st_size or span[1]-span[0]>65536):
                    raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_BOUNDED_ORIGINAL_REQUIRED")
                with body.open("rb") as stream:stream.seek(span[0]);raw=stream.read(span[1]-span[0])
                if raw!=pinned(item["original_fragment_ref"]).read_bytes():raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_ORIGINAL_BYTES_CHANGED")
                parser=FilingText();parser.feed(raw.decode("utf-8"));text=normalized(" ".join(parser.parts))
                if (text!=item["text"] or cash._hash(text)!=item["text_typed_content_sha256"]
                        or pinned(item["text_projection_ref"]).read_text(encoding="utf-8").removesuffix("\n")!=text):
                    raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_ORIGINAL_TEXT_CHANGED")
                return raw,text
            subject=pinned(annual_support["subject_original_HTTP_ref"]);unit_body=pinned(annual_support["unit_original_HTTP_ref"])
            gh,_=original_part(subject,annual_support["subject_actual_SEC_header"]);kh,_=original_part(unit_body,annual_support["unit_actual_SEC_header"])
            for body,header,publication,marker in ((subject,gh,annual_support["subject_actual_publication_date"],b"SUBJECT COMPANY:"),(unit_body,kh,annual_support["unit_source_actual_publication_date"],b"FILER:")):
                pub=cash._day(publication,"annual_actual_SEC_filed_date")
                with body.open("rb") as stream:prefix=stream.read(min(65536,body.stat().st_size))
                section=header.split(marker,1)[-1].split(b"FILED BY:",1)[0]
                if (header not in prefix or header.count(marker)!=1 or pub>prior
                        or re.search(rb"FILED AS OF DATE:\s*"+pub.strftime("%Y%m%d").encode()+rb"\b",header) is None
                        or re.search(rb"CENTRAL INDEX KEY:\s*0*"+str(cik).encode()+rb"\b",section) is None
                        or re.search(rb"COMPANY CONFORMED NAME:\s*"+re.escape(legal.encode())+rb"\s",section) is None):
                    raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_REAL_SEC_SUBJECT_REQUIRED")
            cover_raw,_=original_part(subject,annual_support["subject_original_native_XML_cover"])
            cover=ET.fromstring(b'<r xmlns:com="http://www.sec.gov/edgar/common">'+cover_raw+b'</r>')[0]
            values=lambda tag:[x.text for x in cover.iter() if x.tag.rsplit('}',1)[-1]==tag]
            titles=values("securitiesClassTitle")
            if (values("issuerCik")!=[str(cik).zfill(10)] or len(values("issuerName"))!=1 or key(values("issuerName")[0])!=key(legal)
                    or values("issuerCusip")!=[row["cusip"]] or len(titles)!=1
                    or re.fullmatch(r"Common Stock, par value [$][0-9]+[.][0-9]+",titles[0]) is None):
                raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_NATIVE_SUBJECT_COMMON_CUSIP_REQUIRED")
            parts=annual_support["unit_source_fragments"]
            if set(parts)!={"registrant","US_charter","USD_share_unit","payable_per_share_tag","common_declaration","cash_policy","common_listing"}:
                raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_EXACT_COMMON_MONETARY_CONTEXT_REQUIRED")
            texts={name:original_part(unit_body,item)[1] for name,item in parts.items()}
            unit=pinned(parts["USD_share_unit"]["original_fragment_ref"]).read_bytes();tag=pinned(parts["payable_per_share_tag"]["original_fragment_ref"]).read_bytes()
            unit_match=re.fullmatch(rb'<unit id="([A-Za-z][A-Za-z0-9_]*)">\s*<divide>\s*<unitNumerator>\s*<measure>iso4217:USD</measure>\s*</unitNumerator>\s*<unitDenominator>\s*<measure>shares</measure>\s*</unitDenominator>\s*</divide>\s*</unit>',unit)
            amount_tag=re.fullmatch(rb'<us-gaap:DividendsPayableAmountPerShare\b(?P<attrs>[^>]*)>(?P<amount>[0-9]+[.][0-9]+)</us-gaap:DividendsPayableAmountPerShare>',tag)
            declaration=re.fullmatch(r"On (?P<board>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2}), the Board approved a dividend of [$] (?P<amount>[0-9]+[.][0-9]+) per share for the Company[’']s common stock[.] The dividend will be paid to stockholders of record on (?P<record>[A-Z][a-z]+ [0-9]{1,2}, 20[0-9]{2})[.]",texts["common_declaration"])
            listed=re.fullmatch(r'Our common stock is traded on the (?P<venue>NYSE American|New York Stock Exchange|Nasdaq) under the symbol [“"](?P<ticker>[A-Z][A-Z0-9]*(?:[.][A-Z0-9]+)*)[.]?[”"][.]?',texts["common_listing"])
            venue_map={"NYSE American":"NYSE_AMERICAN","New York Stock Exchange":"NYSE","Nasdaq":"NASDAQ"}
            if (key(texts["registrant"])!=key(legal) or not re.fullmatch(_US_CHARTER_STATE_NAMES,texts["US_charter"],re.I)
                    or listed is None or venue_map[listed.group("venue")]+":"+listed.group("ticker")!=t["listing"]
                    or annual_support.get("source_listing_identity")!=t["listing"] or unit_match is None or amount_tag is None
                    or b'unitRef="'+unit_match.group(1)+b'"' not in amount_tag.group("attrs")
                    or declaration is None or Decimal(declaration.group("amount"))!=Decimal(amount_tag.group("amount").decode())
                    or cash._day(declaration.group("board"),"annual_private_board_day")>cash._day(annual_support["unit_source_actual_publication_date"],"annual_unit_filed_day")
                    or "Any future determination to declare cash dividends will be made at the discretion of the Board" not in texts["cash_policy"]):
                raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_ACTUAL_COMMON_MONETARY_UNIT_REQUIRED")
            fixed_annual_common_binding=dict(status="PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT",source_CUSIP=row["cusip"],source_common_class_literal="Common Stock",original_frozen_class_literal=row["title_of_class"],no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=legal,source_listing_identity=t["listing"],source_US_context_literal=texts["US_charter"],common_amount=float(Decimal(declaration.group("amount"))),common_record_date=str(cash._day(declaration.group("record"),"annual_common_record").date()),fixed_single_annual_payment=True,annualized_rate_conversion=False,fixed_annual_common_cash_support_ref=annual_ref,available_at=None,historical_availability_authority="UNKNOWN",share_quantity_effect=False)
            separate_common_binding=fixed_annual_common_binding

        support_ref=context.get("separate_common_cusip_usd_share_unit_support_ref")
        if support_ref is not None:
            support=json.loads(pinned(support_ref).read_text(encoding="utf-8"));flags=("strict_PIT","production_qualified","quote_qualified","certified_NAV")
            if (not dated_common or sec_linked or supplement is not None
                    or support.get("schema")!="B_SEPARATE_ORIGINAL_ISSUER_REGULAR_CASH_COMMON_CUSIP_USD_SHARE_UNIT_SUPPORT_V1"
                    or support.get("source_role")!="SEPARATE_PRE2026_SEC_COMMON_CUSIP_AND_ISSUER_USD_COMMON_SHARE_UNIT_NO_FAKE_SAME_FILE_CASH"
                    or support.get("same_file_cash_claim") is not False or support.get("same_announcement_common_word_claim") is not False
                    or support.get("available_at") is not None or support.get("historical_availability_authority")!="UNKNOWN"
                    or support.get("actual_exchange_ex_authority")!="UNKNOWN" or support.get("independent_actual_ex_date") is not None
                    or support.get("share_quantity_effect") is not False or any(support.get(k) is not False for k in flags)):
                raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_COMMON_UNIT_SCOPE_REQUIRED")
            frozen=json.loads(pinned(payload["frozen_account_identity_ref"]).read_text(encoding="utf-8"))
            prior=cash._day(entry["prior_raw_close"]["prior_date"],"prior_identity_coordinate")
            matches=[x["original_source_row"] for x in frozen["rows"] if cash._day(x["original_source_row"]["effective_start"],"old_start")<=prior<=cash._day(x["original_source_row"]["effective_end"],"old_end")]
            if len(matches)!=1:raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_UNIQUE_PRIOR_IDENTITY_REQUIRED")
            def proof_fragment(item,body):
                span=item["original_byte_range"]
                if (not isinstance(span,list) or len(span)!=2 or any(type(n) is not int for n in span)
                        or not 0<=span[0]<span[1]<=body.stat().st_size or span[1]-span[0]>65536):
                    raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_BOUNDED_FRAGMENT_REQUIRED")
                with body.open("rb") as stream:stream.seek(span[0]);raw=stream.read(span[1]-span[0])
                if raw!=pinned(item["original_fragment_ref"]).read_bytes():raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_ORIGINAL_BYTES_CHANGED")
                parser=FilingText();parser.feed(raw.decode("utf-8"));text=normalized(" ".join(parser.parts))
                if (text!=item["text"] or pinned(item["text_projection_ref"]).read_text(encoding="utf-8").removesuffix("\n")!=text
                        or cash._hash(text)!=item["text_typed_content_sha256"]):
                    raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_ORIGINAL_TEXT_CHANGED")
                return text
            legal=support["legal_issuer_literal"];cik=support["issuer_CIK"];key=lambda value:re.sub(r"[\s.,]+","",value).casefold()
            if type(cik) is not int or cik<=0:raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_REAL_ISSUER_CIK_REQUIRED")
            subject_payload=dict(payload,source_common_CUSIP_identity_custody_ref=support["subject_identity_ref"])
            _,subject,_,reit=_source_subject_cusip_identity(subject_payload,entry,dict(original_source_row=matches[0]),legal,cik,dict(name=support["source_subject_conformed_name_literal"]),pinned=pinned,fragment=proof_fragment)
            body=pinned(support["unit_original_HTTP_ref"]);header=pinned(support["unit_original_SEC_header_ref"]).read_bytes()
            with body.open("rb") as stream:prefix=stream.read(min(65536,body.stat().st_size))
            day=cash._day(support["unit_source_actual_publication_date"],"separate_SEC_filed_date")
            if (reit or header.rstrip(b"\r\n") not in prefix or header.count(b"FILER:")!=1
                    or re.search(rb"FILED AS OF DATE:\s*"+day.strftime("%Y%m%d").encode()+rb"\b",header) is None
                    or re.search(rb"CENTRAL INDEX KEY:\s*0*"+str(cik).encode()+rb"\b",header) is None
                    or not day<pd.Timestamp("2026-01-01")):
                raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_REAL_UNIT_SEC_HEADER_REQUIRED")
            parts=support["fragments"]
            if set(parts)!={"registrant","US_charter","USD_share_unit","common_dividend_unit_tag","common_listing","common_dividend_policy"}:
                raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_EXACT_UNIT_CONTEXT_REQUIRED")
            texts={name:proof_fragment(item,body) for name,item in parts.items()}
            listing=re.findall(r"\b([A-Z][A-Z0-9.\-]*) (?:The )?(New York Stock Exchange|Nasdaq(?: Global Select Market| Global Market| Capital Market| Stock Market)?)\b",texts["common_listing"])
            unit_raw=pinned(parts["USD_share_unit"]["original_fragment_ref"]).read_bytes();unit=re.fullmatch(rb'<xbrli:unit id="([A-Za-z][A-Za-z0-9_]*)"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>',unit_raw)
            tag=pinned(parts["common_dividend_unit_tag"]["original_fragment_ref"]).read_bytes()
            if (key(texts["registrant"])!=key(legal) or key(entry["identity_binding"]["issuer"])!=key(legal)
                    or not re.fullmatch(_US_CHARTER_STATE_NAMES,texts["US_charter"],re.I)
                    or len(listing)!=1 or len(re.findall(r"\bCommon Stock\b",texts["common_listing"],re.I))!=1
                    or re.search(r"\bpreferred|depositary|ADS|warrant\b",texts["common_listing"],re.I)
                    or support["source_listing_identity"]!=("NYSE:" if listing[0][1]=="New York Stock Exchange" else "NASDAQ:")+listing[0][0]
                    or support["source_listing_identity"]!=t["listing"] or unit is None
                    or b'name="us-gaap:CommonStockDividendsPerShareDeclared"' not in tag
                    or b'unitRef="'+unit.group(1)+b'"' not in tag
                    or "dividends on the shares of common stock" not in texts["common_dividend_policy"]
                    or support.get("unit_tag_role")!="US_GAAP_COMMON_STOCK_DIVIDENDS_PER_SHARE_DECLARED_USD_SHARE_UNIT_ONLY_NOT_ANNUAL_AMOUNT_OR_RATE_CONVERSION"):
                raise ValueError("CA_FROZEN_NAMESPACE_SEPARATE_ISSUER_COMMON_USD_SHARE_UNIT_REQUIRED")
            separate_common_binding=dict(status="PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT",source_common_class_literal="Common Stock",source_CUSIP=subject["raw_CUSIP_literal"],original_frozen_class_literal=matches[0]["title_of_class"],no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=legal,source_listing_identity=support["source_listing_identity"],source_US_context_literal=texts["US_charter"],source_common_CUSIP_identity_custody_ref=support["subject_identity_ref"],separate_common_cusip_usd_share_unit_support_ref=support_ref,available_at=None,historical_availability_authority="UNKNOWN",share_quantity_effect=False)
        current=_original_dated_common_cash_terms(source,pinned=pinned,same_file_identity_source=supplement,source_custody_ref=source_ref,frozen_original_issuer_literal=entry["identity_binding"]["issuer"],sec_parent_exhibit_fact=linked_fact,sec_parent_exhibit_locator_ref=context.get("sec_parent_exhibit_locator_ref"),separate_common_binding=None if fixed_annual_common_binding is not None else separate_common_binding,fixed_annual_common_binding=fixed_annual_common_binding)
        if sec_linked and (payload.get("source_url")!=current["primary_source_url"]
                or payload.get("source_manifest_custody_ref")!=source_ref
                or payload.get("source_transport_metadata",{}).get("full_HTTP_sha256")!=current["source_full_HTTP_sha256"]
                or payload.get("source_transport_metadata",{}).get("full_HTTP_bytes")!=current["source_full_HTTP_bytes"]
                or payload.get("source_transport_metadata",{}).get("full_HTTP_body_locally_available") is not True):
            raise ValueError("CA_SEC_PARENT_EXHIBIT_EXACT_PARENT_HTTP_TRANSPORT_REQUIRED")
        if (any(current[k]!=t[k] for k in ("issuer","ticker","listing","amount","record","pay","publication","currency_basis"))
                or current["body_ref"]!=raw_ref or current["source_paragraph"]!=literal
                or current["source_original_typed_text_digest"]!=digest
                or payload.get("source_original_cash_unit_literal")!=current["original_source_unit_literal"]
                or context.get("US_context_literal")!=current["source_US_context_literal"]
                or context.get("common_unit_context_literal")!=current["original_source_unit_literal"]
                or payload.get("currency")!="USD" or payload.get("source_declared_ex_date") is not None
                or payload.get("ex_directly_declared") is not False or t["available"] is not None):
            raise ValueError("CA_FROZEN_NAMESPACE_DATED_COMMON_EXACT_SOURCE_TERMS_REQUIRED")
        if fixed_annual_common_binding is not None:
            if (payload.get("issuer_observed_ex_date")!=current["issuer_observed_ex_date"]
                    or payload.get("issuer_observed_ex_source_ref")!=current["issuer_observed_ex_source_ref"]
                    or payload.get("source_disagreement_preserved") is not True
                    or annual_support.get("issuer_observed_ex_date")!=current["issuer_observed_ex_date"]
                    or annual_support.get("issuer_observed_ex_source_ref")!=current["issuer_observed_ex_source_ref"]
                    or payload.get("source_declared_ex_date_role")!=current["source_declared_ex_date_role"]
                    or payload.get("annualized_rate_conversion") is not False
                    or payload.get("annual_fixed_single_payment") is not True):
                raise ValueError("CA_FROZEN_NAMESPACE_ANNUAL_ISSUER_EX_OBSERVATION_MUST_SURVIVE")
        same_file_proof=dict(current,cash_source_custody_ref=source_ref,source_identity_context_role=context["role"],
            accounting_classification="EXPLICIT_SOURCE_REGULAR_OR_QUARTERLY_COMMON_CASH",source_classification_is_not_annual_rate=True)
        if separate_common_binding is not None:
            same_file_proof.update(accounting_classification="REGULAR_QUARTERLY_CASH_WITH_SEPARATE_EXACT_COMMON_CUSIP_USD_SHARE_UNIT_SUPPORT",separate_common_unit_binding=copy.deepcopy(separate_common_binding),same_file_cash_common_claim=False,annual_dividend_amount_or_rate_consumed=False)

        if fixed_annual_common_binding is not None:
            same_file_proof.update(accounting_classification="FIXED_SINGLE_ANNUAL_COMMON_MONETARY_PAYMENT_RESEARCH",separate_common_unit_binding=copy.deepcopy(fixed_annual_common_binding),same_file_cash_common_claim=False,annual_dividend_amount_or_rate_consumed=True,annualized_rate_conversion=False,source_disagreement_preserved=True,issuer_observed_ex_date=current["issuer_observed_ex_date"],issuer_observed_ex_source_ref=current["issuer_observed_ex_source_ref"])

    ib=entry["identity_binding"]
    facts=dict(ticker=t["ticker"],security_id=ib["security_id"],listing_identity=t["listing"])
    identity=_existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=ib["issuer"],
        source_common_class_binding=(separate_common_binding if separate_common_binding is not None else dict(original_frozen_class_literal=context.get("original_frozen_class_literal"),
            source_common_class_literal=current["source_common_cover_class_literal"],source_body_common_class_binding=copy.deepcopy(same_file_proof))
            if (separate_common_binding is not None or (dated_common and current["source_common_cover_class_literal"] is not None)) else None))
    if identity is None:raise ValueError("CA_FROZEN_NAMESPACE_ORIGINAL_COM_REQUIRED")
    for ref in refs:pinned(ref)
    binding=dict(status="EXACT_FROZEN_RAW_COMMON_NAMESPACE_BOUND",
        identity_transport_role=FROZEN_COMMON_NAMESPACE_ROLE,source_legal_issuer_literal=t["issuer"],
        original_frozen_issuer_literal=identity["original_source_row"]["issuer_name"],
        source_listing_literal=context["listing_literal"],source_common_unit_literal=context["common_unit_context_literal"],
        issuer_name_alias_used=False,original_declaration_ref=raw_ref,
        original_frozen_identity_ref=payload["frozen_account_identity_ref"],
        frozen_account_identity_binding=identity,available_at=None,historical_availability_authority="UNKNOWN",
        no_current_legal_identity_authority=True,strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
    if fixed_annual_common_binding is not None:binding.update(issuer_observed_ex_date=current["issuer_observed_ex_date"],issuer_observed_ex_source_ref=current["issuer_observed_ex_source_ref"],source_disagreement_preserved=True,operative_research_ex_date=payload["candidate_ex_date"],operative_independent_ex_authority="UNKNOWN",research_configuration_change="FIXED_SINGLE_ANNUAL_MONETARY_COMMON_PAYMENT_SOURCE_BINDING_WITH_ORIGINAL_NORMAL_TPLUS1_CLOCK")
    if same_file_proof is not None:binding["sec_parent_linked_exhibit_binding" if sec_linked else "dated_common_declaration_binding" if dated_common else "dated_common_stock_cents_binding" if dated_cents else "same_file_issuer_filing_binding"]=same_file_proof
    return identity,binding



NYSE_POST_T1_NONBUSINESS_SCOPE=dict(POST_VERIFIED_SCOPE,
    policy_id="NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH",record_from_inclusive="2024-05-29",
    coordinate_role="SOURCE_BOUND_GENERAL_NORMAL_COMMON_CASH_RULE_MATCHED_EXACT_FROZEN_KEY",
    calendar_role="ORIGINAL_FROZEN_RESEARCH_SESSIONS_NOT_INDEPENDENT_NYSE_CERTIFIED_CALENDAR",
    actual_exchange_ex_authority="UNKNOWN",exchange_notice_authority="UNKNOWN",historical_availability_authority="UNKNOWN",
    no_calendar_insertion=True,no_double_holiday_shift=True,exchange_may_direct_otherwise_preserved=True)

def _source_bound_nyse_post_t1_nonbusiness_record(payload,entry,*,calendar,calendar_binding,scope,source_ref_transport=()):
    ref=payload.get("nyse_post_t1_nonbusiness_record_binding_ref")
    if ref is None:return None
    if (scope!=NYSE_POST_T1_NONBUSINESS_SCOPE or payload.get("frozen_common_namespace_role")!=FROZEN_COMMON_NAMESPACE_ROLE
            or payload.get("source_identity_context",{}).get("role")!=DATED_COMMON_DECLARATION_ROLE
            or payload.get("listing_identity","").split(":")[0]!="NYSE"):
        raise ValueError("CA_NYSE_POST_T1_EXPLICIT_NORMAL_COMMON_CASH_SCOPE_REQUIRED")
    refs=payload["source_context_refs"]
    def pinned(r):
        if sum(x==r for x in refs)!=1:raise ValueError("CA_NYSE_POST_T1_EXACT_SOURCE_PIN_REQUIRED")
        return _pin(next((x["custody_ref"] for x in source_ref_transport if x["original_ref"]==r),r))
    binding=json.loads(pinned(ref).read_text(encoding="utf-8"))
    if (binding.get("calendar_binding")!=calendar_binding or binding.get("exact_original_frozen_event_key") not in entry["original_unsupported_keys"]
            or len(entry["original_unsupported_keys"])!=1 or binding.get("record_date")!=payload["record_date"]):
        raise ValueError("CA_NYSE_POST_T1_ORIGINAL_CALENDAR_AND_KEY_REQUIRED")
    source=json.loads(pinned(binding["rule_source_ref"]).read_text(encoding="utf-8"))
    accepted=json.loads(pinned(binding["accepted_original_rule_source_ref"]).read_text(encoding="utf-8"))
    official="https://www.nyse.com/publicdocs/nyse/markets/nyse/rule-filings/filings/2024/SR-NYSE-2024-19.pdf"
    pdf_ref=binding["original_rule_pdf_ref"];pdf=pinned(pdf_ref)
    transport=json.loads(pinned(accepted["transport_ref"]).read_text(encoding="utf-8"))
    if (source.get("schema")!="B_EXISTING_NYSE_POST_T1_EXACT_NECESSARY_RULE_PAGES_SOURCE_ONLY_V1"
            or source.get("official_source_url")!=official or source.get("source_document_year")!=2024
            or source.get("original_rule_pdf_ref")!=pdf_ref
            or {k:accepted["original_ref"][k] for k in ("path","sha256")}!=pdf_ref
            or accepted.get("schema")!="OFFICIAL_PRE2026_NYSE_RULE235_NECESSARY_PAGE_SOURCE_FACTS_V1"
            or transport.get("actual_status")!=200 or transport.get("request_url")!=official
            or transport.get("source_role")!="NYSE_OFFICIAL_PRE2026_RULE_FILING"
            or transport.get("original_HTTP_ref")!=accepted["original_ref"]
            or any(source.get(k) is not False for k in ("strict_PIT","quote_qualified","certified_NAV"))
            or source.get("actual_exchange_ex_authority")!="UNKNOWN" or source.get("exchange_notice_authority")!="UNKNOWN"
            or source.get("historical_availability_authority")!="UNKNOWN"):
        raise ValueError("CA_NYSE_POST_T1_ORIGINAL_OFFICIAL_RULE_SOURCE_REQUIRED")
    from scripts.storage.refresh_sec_event_originals import load_pdf_package
    extractor=source["extractor"]
    if (extractor["path"]!=accepted["extractor"]["path"] or extractor["version"]!=accepted["extractor"]["version"]
            or extractor["existing_accepted_tree_sha256"]!=accepted["extractor"]["source_tree_sha256"]):
        raise ValueError("CA_NYSE_POST_T1_ACCEPTED_RULE_EXTRACTOR_REQUIRED")
    reader_type,actual_extractor=load_pdf_package(Path(extractor["path"]))
    if actual_extractor!=accepted["extractor"]:
        raise ValueError("CA_NYSE_POST_T1_ACTUAL_RULE_EXTRACTOR_CHANGED")
    reader=reader_type(str(pdf));pages=source["selected_pages"]
    if len(reader.pages)!=25 or [p["page_zero_based"] for p in pages]!=[5,7,21,23]:
        raise ValueError("CA_NYSE_POST_T1_EXACT_NECESSARY_RULE_PAGES_REQUIRED")
    text={}
    for page in pages:
        t=reader.pages[page["page_zero_based"]].extract_text() or "";raw=t.encode("utf-8")
        if (t!=page["text"] or hashlib.sha256(raw).hexdigest()!=page["original_extract_text_utf8_sha256"]
                or pinned(page["text_ref"]).read_bytes() not in (raw,raw+b"\n")):
            raise ValueError("CA_NYSE_POST_T1_ORIGINAL_RULE_PAGE_CHANGED")
        text[page["page_zero_based"]]=" ".join(t.split())
    if ("Tuesday, May 28, 2024" not in text[5] or "May 28, 2024 May 24, 2024" not in text[5]
            or "May 29, 2024 May 29, 2024" not in text[5] or "effective upon filing" not in text[7]
            or "Rule shall apply for the [second] preceding business day" not in text[21]
            or "The Exchange may, however, in any specific case, direct otherwise." not in text[21]
            or "Labor Day (1st Mon. in Sept.)" not in text[23]):
        raise ValueError("CA_NYSE_POST_T1_EFFECTIVE_TRANSITION_NORMAL_RULE_REQUIRED")
    ex,_=cash.normal_cash_ex_date(payload["record_date"],calendar,scope_end_exclusive="2026-01-01",
        policy=cash.NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH,nyse_post_t1_nonbusiness_record_binding=binding)
    if str(ex.date())!=payload["candidate_ex_date"]:raise ValueError("CA_NYSE_POST_T1_EXACT_ORIGINAL_COORDINATE_REQUIRED")
    return binding

def _historical_python_code_custody_transport(bundle):
    """Validate each historical code-byte relocation against its own frozen parent."""
    from scripts.common.storage_paths import resolve,resolve_cache_path
    updates=bundle.get("exact_historical_python_code_custody_transport",())
    if not isinstance(updates,(tuple,list)):
        raise ValueError("CA_EXACT_HISTORICAL_CODE_CUSTODY_REQUIRED")
    repo=resolve().repo_root.resolve()
    custody_root=resolve_cache_path("V24","V24_B_FAST_TRACK_PAIR_COMPLETION_R1","source_audit","original_frozen")
    accepted=[];subjects=[]
    for tx in updates:
        if not isinstance(tx,dict):raise ValueError("CA_EXACT_HISTORICAL_CODE_CUSTODY_REQUIRED")
        original,custody,parent=tx.get("original_ref"),tx.get("custody_ref"),tx.get("predecessor_source_contract_ref")
        if (not all(isinstance(r,dict) and set(r)=={"path","sha256"} for r in (original,custody,parent))
                or not re.fullmatch(r"[0-9a-f]{64}",original["sha256"])
                or tx.get("transport_purpose")!="EXACT_HISTORICAL_REPOSITORY_PYTHON_CODE_BYTES_ONLY"
                or any(tx.get(k) is not True for k in ("original_bytes_unchanged","original_ref_present_in_predecessor_source_refs","old_ref_not_relabelled_as_current_producer"))
                or original["sha256"]!=custody["sha256"] or original in subjects
                or Path(original["path"]).suffix.lower()!=".py"
                or not Path(original["path"]).resolve().is_relative_to(repo)
                or Path(custody["path"]).resolve()!=(custody_root/(Path(original["path"]).stem+"_"+original["sha256"]+".py")).resolve()
                or original in bundle["source_refs"] or sum(r==custody for r in bundle["source_refs"])!=1):
            raise ValueError("CA_EXACT_HISTORICAL_CODE_BYTES_TRANSPORT_REQUIRED")
        predecessor=_read(parent)
        if (predecessor.get("schema")!=SCHEMA or predecessor.get("status")!="FROZEN"
                or sum(r==original for r in predecessor.get("source_refs",()))!=1):
            raise ValueError("CA_EXACT_HISTORICAL_CODE_PARENT_REQUIRED")
        _pin(custody);subjects.append(original);accepted.append(tx)
    return tuple(accepted)


POST_NATIVE_DATED_RAW_CASH_SCOPE=dict(
    role="POST_NATIVE_EXACT_DATED_RAW_CASH_NAMESPACE_R1",
    original_source_producer="B_CA_SOURCE_ACCOUNT_FAST_TRACK_V38_R1",
    original_fact_payload_rewritten=False,original_profile_validation_preserved=True,
    share_quantity_effect=False,new_legal_CUSIP_authority=False,
    alpha_or_label_expansion=False,strict_PIT=False)


def _post_native_cash_raw_namespace(owner,event,entry,identity,bridge,*,native_proof):
    """Map a completely native-validated cash event; its original facts stay intact."""
    from dataclasses import replace
    import pyarrow.parquet as pq
    if (bridge.get("schema")!="V38_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R1"
            or bridge.get("original_fact_ref")!=entry["fact_ref"]
            or bridge.get("original_frozen_identity_ref")!=entry.get("frozen_account_identity_ref")
            or bridge.get("original_security_id")!=event.old_security_id
            or bridge.get("ticker")!=event.ticker or bridge.get("ex_date")!=event.ex_date
            or bridge.get("same_pre_ex_and_ex_UID_and_SID") is not True
            or bridge.get("prior_raw_close_current_matches_legacy") is not True
            or bridge.get("raw_row_present") is not True
            or any(bridge.get(k) is not False for k in ("issuer_CIK_is_security_UID","new_legal_CUSIP_authority",
                "old_source_producer_relabelled","payload_security_id_rewritten","share_quantity_effect"))
            or bridge.get("source_coordinate")!="RAW_ACTUAL_SHARE"
            or type(event) is not owner._frozen_ca_module.ResearchReconstructedCashEvent
            or event.action_type!="CASH_DIVIDEND" or event.currency!="USD"
            or event.amount_unit!=cash.USD_PER_RAW_OLD_SHARE
            or event.quantity_coordinate!=cash.RAW_OLD_SHARE_COORDINATE):
        raise ValueError("CA_POST_NATIVE_EXACT_ORIGINAL_CASH_BRIDGE_REQUIRED")
    if (native_proof.get("original_fact_ref")!=entry["fact_ref"]
            or native_proof.get("original_typed_event")!=asdict(event)
            or native_proof.get("original_event_fingerprint")!=event.event_fingerprint
            or native_proof.get("original_payload_unchanged") is not True
            or native_proof.get("native_economic_fields_unmodified") is not True):
        raise ValueError("CA_POST_NATIVE_ORIGINAL_TYPED_PROOF_CHANGED")
    refs=bridge["source_refs"];allowed=("calendar_ref","dated_identity_ref","mapping_ref","identity_projection_ref","raw_price_ref")
    if set(refs)!=set(allowed):raise ValueError("CA_POST_NATIVE_EXACT_SOURCE_REFS_REQUIRED")
    for r in refs.values():_pin(r)
    raw_payload=dict(static_submission_dated_raw_identity_binding=dict(
        schema="STATIC_SEC_EXACT_DATED_RAW_COMMON_UID_BRIDGE_V1",
        role="EXACT_DATED_FROZEN_COM_AND_STATIC_UNIQUE_COMMON_SYMBOL",ticker=event.ticker,
        source_coordinate="RAW_ACTUAL_SHARE",new_legal_CUSIP_authority=False,issuer_CIK_is_security_UID=False,
        share_quantity_effect=False,**{k:refs[k] for k in allowed if k!="raw_price_ref"}),source_refs=list(refs.values()))
    facts=dict(ticker=event.ticker,security_id=bridge["accounting_sid"],exact_frozen_event_key=entry["original_unsupported_keys"][0])
    dated=_static_submission_dated_raw_identity(raw_payload,entry,facts,identity,pinned=_pin)
    if dated["security_uid"]!=bridge["security_uid"] or dated["prior_date"]!=bridge["prior_date"]:
        raise ValueError("CA_POST_NATIVE_ORIGINAL_DATED_UID_CHANGED")
    actual_links=[dict(ticker=event.ticker,signal_date=d,security_uid=dated["security_uid"],accounting_sid=dated["accounting_sid"])
        for d in (dated["prior_date"],dated["ex_date"])]
    if actual_links!=bridge["identity_links"]:raise ValueError("CA_POST_NATIVE_DATED_MAPPER_RESULT_CHANGED")
    price_path=_pin(refs["raw_price_ref"]);pf=pq.ParquetFile(price_path)
    for index in range(pf.metadata.num_row_groups):
        g=pf.metadata.row_group(index);col=next(g.column(j) for j in range(g.num_columns) if g.column(j).path_in_schema=="trade_date")
        if (col.statistics is None or not col.statistics.has_min_max or col.statistics.min is None or col.statistics.max is None
                or pd.isna(pd.Timestamp(col.statistics.min)) or pd.isna(pd.Timestamp(col.statistics.max))
                or pd.Timestamp(col.statistics.max)>=pd.Timestamp("2026-01-01")):
            raise ValueError("CA_POST_NATIVE_RAW_PRICE_PHYSICAL_PRE2026_REQUIRED")
    raw=pq.read_table(price_path,columns=["ticker","trade_date","close"],filters=[("ticker","=",event.ticker),
        ("trade_date","=",pd.Timestamp(dated["prior_date"])),("trade_date","<",pd.Timestamp("2026-01-01"))]).to_pylist()
    if (len(raw)!=1 or raw[0]["close"]!=entry["prior_raw_close"]["raw_close"]
            or entry["prior_raw_close"]["prior_date"]!=dated["prior_date"]):
        raise ValueError("CA_POST_NATIVE_RAW_ENDPOINT_CHANGED")
    converted=replace(event,source_scope="B_FROZEN_PRE2026_ACCOUNTING_ONLY",old_security_id=dated["accounting_sid"],
        event_id="SOURCE_CASH_RAW_NAMESPACE:"+_hash(dict(original_event_fingerprint=event.event_fingerprint,accounting_sid=dated["accounting_sid"])))
    old,new=asdict(event),asdict(converted)
    if any(old[k]!=new[k] for k in old if k not in ("old_security_id","event_id")):
        raise ValueError("CA_POST_NATIVE_CASH_ECONOMICS_CHANGED")
    return converted,dict(role=POST_NATIVE_DATED_RAW_CASH_SCOPE["role"],original_typed_event=old,
        original_event_fingerprint=event.event_fingerprint,projected_event_fingerprint=converted.event_fingerprint,
        original_fact_ref=copy.deepcopy(entry["fact_ref"]),original_identity=copy.deepcopy(identity),
        dated_raw_identity_proof=dated,source_refs=copy.deepcopy(refs),cash_economic_fields_unchanged=True,
        original_small_cash_adjudication_preserved_with_identical_raw_endpoint=True,
        old_source_producer_relabelled=False,original_fact_payload_rewritten=False,share_quantity_effect=False)


def bind_source_account_descendant(owner, original_events, bundle, *, account_dates, bundle_ref=None):
    """Return new event kwargs, exact removal evidence and approved clock scope.

    The input catalogue and source facts are immutable. Only complete original
    transform records with a unique independently verified ordinary cash event
    are removed; other same-day diagnostics and all unresolved events survive.
    """
    if bundle.get("schema") != SCHEMA or bundle.get("status") != "FROZEN" or bundle.get("clock_convention") != CLOCK:
        raise ValueError("CA_FROZEN_SOURCE_ACCOUNT_CONTRACT_REQUIRED")
    if bundle.get("historical_broker_payment_proven") is not False:
        raise ValueError("CA_RESEARCH_CLOCK_CANNOT_PROMOTE_BROKER_AUTHORITY")
    ads_scope_enabled = "source_declared_ads_cash_scope" in bundle
    if ads_scope_enabled:
        scope = bundle["source_declared_ads_cash_scope"]
        if (not isinstance(scope, dict)
                or _hash(scope) != _hash(SOURCE_DECLARED_ADS_CASH_SCOPE)):
            raise ValueError("CA_EXACT_SOURCE_DECLARED_ADS_CASH_SCOPE_REQUIRED")
        if bundle_ref is None or _read(bundle_ref) != bundle:
            raise ValueError("CA_PINNED_SOURCE_DECLARED_ADS_CASH_SCOPE_REQUIRED")
    foreign_common_scope_enabled="foreign_nasdaq_ordinary_same_file_explicit_usd_scope" in bundle
    if foreign_common_scope_enabled and (bundle["foreign_nasdaq_ordinary_same_file_explicit_usd_scope"]!=FOREIGN_COMMON_SCOPE or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_FOREIGN_COMMON_EXACT_PHYSICAL_BUNDLE_SCOPE_REQUIRED")
    late_currency_scope_enabled = "later_same_event_currency_cash_scope" in bundle
    if late_currency_scope_enabled:
        scope = bundle["later_same_event_currency_cash_scope"]
        if (not isinstance(scope, dict)
                or _hash(scope) != _hash(LATE_CURRENCY_SCOPE)
                or bundle_ref is None or _read(bundle_ref) != bundle):
            raise ValueError("CA_EXACT_PINNED_LATE_CURRENCY_SCOPE_REQUIRED")
    issuer_pdf_scope_enabled="issuer_pdf_frozen_common_cash_scope" in bundle
    if issuer_pdf_scope_enabled and (bundle["issuer_pdf_frozen_common_cash_scope"]!=ISSUER_PDF_SCOPE
            or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_ISSUER_PDF_EXACT_PHYSICAL_BUNDLE_SCOPE_REQUIRED")
    sec_cash_scope_enabled = "sec_same_file_cash_fact_scope" in bundle
    if sec_cash_scope_enabled:
        scope = bundle["sec_same_file_cash_fact_scope"]
        if (not isinstance(scope, dict) or _hash(scope) != _hash(SEC_CASH_SCOPE)
                or bundle_ref is None or _read(bundle_ref) != bundle):
            raise ValueError("CA_EXACT_PINNED_SEC_CASH_FACT_SCOPE_REQUIRED")
    sec_html_scope_enabled="sec_primary_html_frozen_common_cash_scope" in bundle
    if sec_html_scope_enabled and (bundle["sec_primary_html_frozen_common_cash_scope"]!=SEC_PRIMARY_HTML_SCOPE
            or not sec_cash_scope_enabled or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_EXACT_PINNED_SEC_PRIMARY_HTML_CASH_SCOPE_REQUIRED")
    sec_submission_scope_enabled="sec_static_submission_common_cash_scope" in bundle
    if sec_submission_scope_enabled and (_hash(bundle["sec_static_submission_common_cash_scope"])!=_hash(SEC_STATIC_SUBMISSION_SCOPE)
            or not sec_cash_scope_enabled or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_EXACT_PINNED_SEC_STATIC_SUBMISSION_CASH_SCOPE_REQUIRED")
    sec_primary_body_scope_enabled="sec_static_primary_body_common_cash_scope" in bundle
    if sec_primary_body_scope_enabled and (_hash(bundle["sec_static_primary_body_common_cash_scope"])!=_hash(SEC_STATIC_PRIMARY_BODY_SCOPE)
            or not sec_cash_scope_enabled or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_EXACT_PINNED_SEC_PRIMARY_BODY_CASH_SCOPE_REQUIRED")
    post_native_raw_scope_enabled="post_native_dated_raw_cash_namespace_scope" in bundle
    post_native_bridges=[];post_native_proofs=[]
    if post_native_raw_scope_enabled:
        bridge_ref=bundle.get("post_native_dated_raw_cash_namespace_bridge_ref")
        if (bundle["post_native_dated_raw_cash_namespace_scope"]!=POST_NATIVE_DATED_RAW_CASH_SCOPE
                or not isinstance(bridge_ref,dict) or bridge_ref not in bundle.get("source_refs",())
                or bundle_ref is None or _read(bundle_ref)!=bundle):
            raise ValueError("CA_PINNED_POST_NATIVE_DATED_RAW_NAMESPACE_SCOPE_REQUIRED")
        packet=_read(bridge_ref)
        if (packet.get("schema")!="V38_REUSED_ORDINARY_DATED_RAW_BRIDGES_R2"
                or packet.get("source_producer")!="B_CA_SOURCE_ACCOUNT_FAST_TRACK_V38_R1"
                or packet.get("current_native_admission") is not False or packet.get("strict_PIT") is not False):
            raise ValueError("CA_POST_NATIVE_ORIGINAL_BRIDGE_PACKET_REQUIRED")
        old_proof_ref=packet.get("old_native_proof_ref")
        if not isinstance(old_proof_ref,dict) or old_proof_ref not in bundle.get("source_refs",()):
            raise ValueError("CA_POST_NATIVE_PINNED_ORIGINAL_TYPED_PROOF_REQUIRED")
        old_proof=_read(old_proof_ref)
        if (old_proof.get("schema")!="V38_REUSED_ORDINARY_OLD_NATIVE_PROOF_R2"
                or old_proof.get("status")!="PASS_24_ORIGINAL_NAMESPACE_FACTS_PENDING_ACCOUNTING_PROJECTION"
                or old_proof.get("strict_PIT") is not False or old_proof.get("fit_or_replay_run") is not False):
            raise ValueError("CA_POST_NATIVE_ORIGINAL_NATIVE_PROOF_REQUIRED")
        producer_ref=packet.get("parent_v38_ref")
        if producer_ref!=old_proof.get("old_producer_ref") or producer_ref not in bundle.get("source_refs",()):
            raise ValueError("CA_POST_NATIVE_ORIGINAL_PRODUCER_CLOSURE_REQUIRED")
        post_native_proofs=old_proof["entries"]
        post_native_bridges=packet["bridges"]
        if len({(r["original_fact_ref"]["path"],r["original_fact_ref"]["sha256"]) for r in post_native_bridges})!=len(post_native_bridges):
            raise ValueError("CA_POST_NATIVE_BRIDGE_FACT_AMBIGUOUS")
    report_cash_scope_enabled = "report_same_file_cash_table_scope" in bundle
    if report_cash_scope_enabled:
        scope=bundle["report_same_file_cash_table_scope"]
        if (not isinstance(scope,dict) or _hash(scope)!=_hash(REPORT_CASH_SCOPE)
                or bundle_ref is None or _read(bundle_ref)!=bundle):
            raise ValueError("CA_EXACT_PINNED_REPORT_CASH_FACT_SCOPE_REQUIRED")
    nyse_post_t1_scope=bundle.get("nyse_post_t1_nonbusiness_record_scope")
    if nyse_post_t1_scope is not None and (bundle.get("frozen_common_cash_namespace_scope")!=FROZEN_COMMON_NAMESPACE_SCOPE or nyse_post_t1_scope!=NYSE_POST_T1_NONBUSINESS_SCOPE):
        raise ValueError("CA_NYSE_POST_T1_EXACT_SOURCE_SCOPE_REQUIRED")
    nyse_nonbusiness_scope=bundle.get("report_nyse_pre_t1_nonbusiness_record_scope")
    if nyse_nonbusiness_scope is not None:
        if not isinstance(nyse_nonbusiness_scope,dict):
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_EXACT_SCOPE_REQUIRED")
        expected=dict(REPORT_NYSE_PRE_T1_NONBUSINESS_SCOPE,rule_source_ref=nyse_nonbusiness_scope.get("rule_source_ref"))
        if (not report_cash_scope_enabled or not isinstance(nyse_nonbusiness_scope,dict)
                or _hash(nyse_nonbusiness_scope)!=_hash(expected)
                or nyse_nonbusiness_scope.get("strict_PIT") is not False
                or not isinstance(expected["rule_source_ref"],dict)
                or set(expected["rule_source_ref"])!={"path","sha256"}):
            raise ValueError("CA_REPORT_NYSE_NONBUSINESS_EXACT_SCOPE_REQUIRED")
    direct_ex_scope_enabled = "source_declared_cash_ex_scope" in bundle
    if direct_ex_scope_enabled:
        scope = bundle["source_declared_cash_ex_scope"]
        if (not isinstance(scope, dict)
                or _hash(scope) != _hash(SOURCE_DECLARED_CASH_EX_SCOPE)):
            raise ValueError("CA_EXACT_SOURCE_DECLARED_CASH_EX_SCOPE_REQUIRED")
        if bundle_ref is None or _read(bundle_ref) != bundle:
            raise ValueError("CA_PINNED_SOURCE_DECLARED_CASH_EX_SCOPE_REQUIRED")
    dated_unit_scope_enabled=bundle.get("dated_notice_frozen_common_unit_scope") is not None
    if dated_unit_scope_enabled and (bundle["dated_notice_frozen_common_unit_scope"]!=DATED_COMMON_UNIT_SCOPE
            or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_DATED_COMMON_UNIT_EXPLICIT_BUNDLE_SCOPE_REQUIRED")
    frozen_namespace_scope_enabled=bundle.get("frozen_common_cash_namespace_scope") is not None
    if frozen_namespace_scope_enabled and (bundle["frozen_common_cash_namespace_scope"]!=FROZEN_COMMON_NAMESPACE_SCOPE
            or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_PINNED_FROZEN_COMMON_NAMESPACE_SCOPE_REQUIRED")
    component_group_scope_enabled=bundle.get("same_clock_common_cash_component_group_scope") is not None
    if component_group_scope_enabled and (bundle["same_clock_common_cash_component_group_scope"]!=COMPONENT_GROUP_SCOPE
            or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_PINNED_EXACT_COMPONENT_GROUP_SCOPE_REQUIRED")
    base_variable_component_scope_enabled=bundle.get("base_variable_common_cash_component_group_scope") is not None
    if base_variable_component_scope_enabled and (bundle["base_variable_common_cash_component_group_scope"]!=BASE_VARIABLE_COMPONENT_SCOPE
            or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_PINNED_EXACT_BASE_VARIABLE_COMPONENT_SCOPE_REQUIRED")
    closed_record_scope_enabled=bundle.get("closed_record_next_session_research_scope") is not None
    if closed_record_scope_enabled and (bundle["closed_record_next_session_research_scope"]!=CLOSED_RECORD_RESEARCH_SCOPE
            or bundle_ref is None or _read(bundle_ref)!=bundle):
        raise ValueError("CA_PINNED_CLOSED_RECORD_RESEARCH_SCOPE_REQUIRED")
    source_ref_transport = bundle.get("inherited_producer_physical_custody_transport", ())
    if not isinstance(source_ref_transport, (tuple, list)):
        raise ValueError("CA_DECLARED_CUSTODY_TRANSPORT_REQUIRED")
    if source_ref_transport:
        if (bundle_ref is None or _read(bundle_ref) != bundle
                or not isinstance(bundle.get("predecessor_source_contract_ref"), dict)):
            raise ValueError("CA_PINNED_CUSTODY_PREDECESSOR_REQUIRED")
        predecessor = _read(bundle["predecessor_source_contract_ref"])
        subjects = []
        for tx in source_ref_transport:
            if not isinstance(tx, dict):
                raise ValueError("CA_DECLARED_CUSTODY_TRANSPORT_REQUIRED")
            original_ref, custody_ref = tx.get("original_ref"), tx.get("custody_ref")
            if (not isinstance(original_ref, dict) or not isinstance(custody_ref, dict)
                    or set(original_ref) != {"path", "sha256"}
                    or set(custody_ref) != {"path", "sha256"}
                    or tx.get("original_bytes_unchanged") is not True
                    or tx.get("old_ref_not_relabelled_as_current_producer") is not True
                    or tx.get("original_ref_present_in_predecessor_source_refs") is not True
                    or original_ref["sha256"] != custody_ref["sha256"]
                    or sum(r == original_ref for r in predecessor.get("source_refs", ())) != 1
                    or original_ref in bundle["source_refs"]
                    or sum(r == custody_ref for r in bundle["source_refs"]) != 1
                    or original_ref in subjects
                    or any(r["path"] == original_ref["path"] for r in subjects)):
                raise ValueError("CA_EXACT_SAME_BYTES_CUSTODY_TRANSPORT_REQUIRED")
            _pin(custody_ref)
            subjects.append(original_ref)
    source_ref_transport=tuple(source_ref_transport)+_historical_python_code_custody_transport(bundle)
    for ref in bundle["source_refs"]:
        _pin(ref)
    _pin(bundle["parent_cash_kwargs_ref"])
    audit = _read(bundle["local_identity_audit_ref"])
    dates = tuple(pd.Timestamp(x) for x in account_dates)
    if (not dates or any(pd.isna(x) or x.tzinfo is not None or x != x.normalize()
                         or not pd.Timestamp("2023-01-01") <= x < pd.Timestamp("2026-01-01") for x in dates)
            or tuple(sorted(set(dates))) != dates):
        raise ValueError("CA_LEGAL_ACCOUNT_CALENDAR_UNIQUE_SORTED_REQUIRED")
    if tuple(str(x.date()) for x in dates) != tuple(audit["calendar"]):
        raise ValueError("CA_SOURCE_ACCOUNT_CALENDAR_CHANGED")
    if len(dates) != 752 or dates[0] != pd.Timestamp("2023-01-03") or dates[-1] != pd.Timestamp("2025-12-31"):
        raise ValueError("CA_EXACT_PRE2026_ACCOUNT_SCOPE_REQUIRED")
    original = tuple(original_events.get("entitlement_events", ()))
    if [e.event_fingerprint for e in original] != bundle["parent_entitlement_event_fingerprints"]:
        raise ValueError("CA_PARENT_TYPED_CATALOGUE_CHANGED")
    typed = list(original)
    ids = {e.event_id for e in original}
    economic = {(e.ticker, e.ex_date) for e in original if e.action_type == "CASH_DIVIDEND"}
    mappings = dict(original_events.get("entitlement_security_tickers", {}))
    unsupported = tuple(copy.deepcopy(original_events.get("unsupported_events", ())))
    key_counts = {}
    for item in unsupported:
        k = _key(item);key_counts[k] = key_counts.get(k, 0)+1
    audit_key_counts = {}
    for item in audit["source_events"]:
        k = _key(item);audit_key_counts[k] = audit_key_counts.get(k, 0)+1
    removed, proofs, post_verified_entries = {}, [], []
    corroborated_parent_ids = set()
    for entry in bundle["events"]:
        ref = entry["fact_ref"];payload = _read(ref)
        post_verified=payload.get("schema")=="B_FROZEN_HISTORY_POST_VERIFIED_CASH_SOURCE_PROJECTION_V1"
        late_currency = payload.get("schema") == "B_FROZEN_HISTORY_LATE_CURRENCY_CASH_SOURCE_PROJECTION_V1"
        sec_cash = payload.get("schema") == "B_FROZEN_HISTORY_SEC_CASH_FACT_SOURCE_PROJECTION_V1"
        report_cash=payload.get("schema")=="B_FROZEN_HISTORY_REPORT_CASH_TABLE_SOURCE_PROJECTION_V1"
        dated_unit=payload.get("schema")=="B_FROZEN_HISTORY_DATED_NOTICE_COMMON_UNIT_BRIDGE_SOURCE_PROJECTION_V1"
        component_group=payload.get("schema")=="B_FROZEN_HISTORY_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_SOURCE_PROJECTION_V1"
        frozen_namespace=payload.get("frozen_common_namespace_role") is not None
        foreign_common=payload.get("schema")=="B_FOREIGN_NASDAQ_ORDINARY_SAME_FILE_USD_CASH_SOURCE_PROJECTION_V1"
        reconstructed_cash = post_verified or late_currency or sec_cash or report_cash or dated_unit or component_group or frozen_namespace or foreign_common
        original_payload=payload
        nyse_post_t1_binding=_source_bound_nyse_post_t1_nonbusiness_record(payload,entry,calendar=dates,
            calendar_binding=bundle.get("historical_calendar_binding"),scope=nyse_post_t1_scope,source_ref_transport=source_ref_transport)
        frozen_namespace_identity=frozen_namespace_binding=None
        if frozen_namespace:
            if not frozen_namespace_scope_enabled:raise ValueError("CA_FROZEN_NAMESPACE_EXPLICIT_SCOPE_REQUIRED")
            frozen_namespace_identity,frozen_namespace_binding=_frozen_common_cash_namespace(payload,entry,source_ref_transport=source_ref_transport)
        if payload.get("closed_record_research_binding_ref") is not None and (not closed_record_scope_enabled or not component_group):
            raise ValueError("CA_CLOSED_RECORD_EXPLICIT_COMPONENT_GROUP_SCOPE_REQUIRED")
        if component_group:
            if payload.get("cash_evidence_role")==BASE_VARIABLE_COMPONENT_ROLE:
                if not base_variable_component_scope_enabled:raise ValueError("CA_BASE_VARIABLE_COMPONENT_EXPLICIT_BUNDLE_SCOPE_REQUIRED")
            elif not component_group_scope_enabled:raise ValueError("CA_COMPONENT_GROUP_EXPLICIT_BUNDLE_SCOPE_REQUIRED")
            payload=_common_cash_component_group_terms(payload,entry,source_ref_transport=source_ref_transport)
        if dated_unit:
            if not dated_unit_scope_enabled:
                raise ValueError("CA_DATED_COMMON_UNIT_EXPLICIT_BUNDLE_SCOPE_REQUIRED")
            payload=_dated_frozen_common_unit_terms(payload,entry,source_ref_transport=source_ref_transport)
        if report_cash:
            if not report_cash_scope_enabled:
                raise ValueError("CA_EXPLICIT_REPORT_CASH_FACT_SCOPE_REQUIRED")
            payload=_report_frozen_cash_terms(payload,entry,source_ref_transport=source_ref_transport,
                nyse_nonbusiness_scope=nyse_nonbusiness_scope,calendar=dates,
                calendar_binding=bundle.get("historical_calendar_binding"))
        if sec_cash:
            if not sec_cash_scope_enabled:
                raise ValueError("CA_EXPLICIT_SEC_CASH_FACT_SCOPE_REQUIRED")
            if payload.get("sec_source_transport_profile")==SEC_PRIMARY_HTML_PROFILE and not sec_html_scope_enabled:
                raise ValueError("CA_EXPLICIT_SEC_PRIMARY_HTML_CASH_SCOPE_REQUIRED")
            if payload.get("sec_source_transport_profile")==SEC_STATIC_SUBMISSION_PROFILE and not sec_submission_scope_enabled:
                raise ValueError("CA_SEC_STATIC_SUBMISSION_BUNDLE_SCOPE_REQUIRED")
            if payload.get("sec_source_transport_profile")==SEC_STATIC_PRIMARY_BODY_PROFILE and not sec_primary_body_scope_enabled:
                raise ValueError("CA_SEC_PRIMARY_BODY_BUNDLE_SCOPE_REQUIRED")
            payload = _sec_frozen_cash_terms(payload,entry,source_ref_transport=source_ref_transport)
        if foreign_common:
            if not foreign_common_scope_enabled:raise ValueError("CA_FOREIGN_COMMON_EXPLICIT_BUNDLE_SCOPE_REQUIRED")
            payload=_foreign_explicit_usd_common_cash_terms(payload,entry,source_ref_transport=source_ref_transport)
        if late_currency:
            if not late_currency_scope_enabled:
                raise ValueError("CA_EXPLICIT_LATE_CURRENCY_SCOPE_REQUIRED")
            payload = _late_currency_terms(payload,entry,source_ref_transport=source_ref_transport)
        if post_verified:
            if payload.get("source_transport_profile")==ISSUER_PDF_PROFILE and not issuer_pdf_scope_enabled:
                raise ValueError("CA_ISSUER_PDF_EXPLICIT_BUNDLE_SCOPE_REQUIRED")
            if bundle.get("post_verified_cash_scope")!=POST_VERIFIED_SCOPE or bundle_ref is None or _read(bundle_ref)!=bundle:
                raise ValueError("CA_EXPLICIT_FROZEN_POST_VERIFIED_BUNDLE_REQUIRED")
            payload=_post_verified_terms(payload,entry,source_ref_transport=source_ref_transport)
        envelope = dict(payload=payload, **ref, guard=dict(status="HASH_VERIFIED_PAYLOAD", **ref, payload_sha256=_hash(payload)))
        guarded, guard = cash._guard(envelope)
        # The explicit ADS admission applies only to source-declared terms.
        # It does not transform or widen the independent post-verified branch.
        t = cash._terms(guarded, allow_ads=ads_scope_enabled and not reconstructed_cash)
        if t["ticker"] == "MKFG":
            raise ValueError("CA_MKFG_TERMINAL_SOURCE_EXCLUDED")
        if (not component_group and payload.get("ordinary_cash_dividend") is not True) or payload.get("currency") != "USD":
            raise ValueError("CA_ONLY_VERIFIED_ORDINARY_USD_CASH_SUPPORTED")
        if not payload.get("source_url", "").startswith(("https://","http://") if post_verified else "https://"):
            raise ValueError("CA_ISSUER_SOURCE_REQUIRED")
        amount = t["amount"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            raise ValueError("CA_SOURCE_POSITIVE_CASH_REQUIRED")
        record = cash._day(t["record"], "record_date")
        pay = cash._day(t["pay"], "pay_date", known_future_schedule=True)
        publication = None if report_cash else cash._day(t["publication"], "publication_date")
        closed_record=payload.get("closed_record_research_binding")
        if closed_record is not None:
            owner._frozen_ca_module.validate_closed_record_research_binding(closed_record,calendar=dates,
                record_date=str(record.date()),pay_date=str(pay.date()),ex_date=t["candidate_ex"])
            if {k:closed_record["calendar_binding"].get(k) for k in bundle["historical_calendar_binding"]}!=bundle["historical_calendar_binding"]:
                raise ValueError("CA_CLOSED_RECORD_ORIGINAL_CALENDAR_BINDING_CHANGED")
        direct_ex = payload.get("ex_directly_declared", False)
        if not isinstance(direct_ex, bool):
            raise ValueError("CA_DIRECT_EX_DECLARATION_FLAG_INVALID")
        source_ex_policy = direct_ex_scope_enabled and direct_ex and (not reconstructed_cash or frozen_namespace)
        cns_binding=payload.get("historical_ex_adjudication_input",{}).get("cns_bank_holiday_record_binding")
        if cns_binding is not None:
            # New NSCC CNS research projection preserves the issuer record date.
            # Source bytes are pinned here; the cash owner validates the fixed rule.
            f=payload["historical_ex_adjudication_input"]
            if (not sec_cash or payload.get("sec_frozen_cash_binding",{}).get("sec_cash_statement_profile")!="SEC_EXPLICIT_CLASS_A_REGULAR_QUARTERLY_COMMON_SHARE_CASH"
                    or bundle.get("cns_bank_holiday_record_policy")!="NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH"
                    or cns_binding.get("calendar_binding")!=bundle["historical_calendar_binding"]
                    or cns_binding.get("exact_original_frozen_event_key")!=entry["original_unsupported_keys"][0]
                    or cns_binding.get("published_record_date")!=str(record.date())
                    or cns_binding.get("issuer_record_source_ref",{}).get("sha256")!=f.get("issuer_source_fingerprint")
                    or cns_binding.get("security_identity_source_ref",{}).get("sha256")!=f.get("identity_source_fingerprint")
                    or cns_binding.get("notice_section_source_sha256")!=cns_binding.get("notice_source_ref",{}).get("sha256")
                    or any(cns_binding.get(k) is not False for k in ("strict_PIT","production_qualified","quote_qualified","certified_NAV"))):
                raise ValueError("CA_CNS_EXPLICIT_ORIGINAL_CALENDAR_SUBJECT_AND_SOURCE_REQUIRED")
            source_refs=original_payload["source_refs"]
            for name in ("notice_source_ref","notice_section_ref","issuer_record_source_ref","security_identity_source_ref"):
                r=cns_binding[name]
                if (not isinstance(r,dict) or set(r)!={"path","sha256"}
                        or sum({k:x[k] for k in ("path","sha256")}==r for x in source_refs)!=1):
                    raise ValueError("CA_CNS_EXACT_SOURCE_PIN_REQUIRED")
                target=next((x["custody_ref"] for x in source_ref_transport if x["original_ref"]==r),r);_pin(target)
        ex, rule_key = cash.normal_cash_ex_date(record, dates,
            scope_end_exclusive="2026-01-01",
            **(dict(policy=cash.NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH,cns_bank_holiday_record_binding=cns_binding)
                if cns_binding is not None else dict(policy=cash.CLOSED_RECORD_RESEARCH_POLICY,closed_record_research_binding=closed_record)
                if closed_record is not None else dict(policy=cash.NYSE_RULE235_POST_T1_NONBUSINESS_RESEARCH,
                nyse_post_t1_nonbusiness_record_binding=nyse_post_t1_binding) if nyse_post_t1_binding is not None else dict(policy="SOURCE_DECLARED_EX_RESEARCH",
                source_declared_ex_date=cash._day(payload.get("source_declared_ex_date"),
                    "source_declared_ex_date")) if source_ex_policy else
                dict(policy=cash.NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH,
                    nyse_nonbusiness_record_binding=payload["historical_ex_adjudication_input"]["nyse_nonbusiness_record_binding"])
                if report_cash and payload["historical_ex_adjudication_input"].get("nyse_nonbusiness_record_binding") is not None else {}))
        # The NYSE transition is a distinct rule requiring its own source.
        if record == pd.Timestamp("2024-05-28"):
            raise ValueError("CA_TRANSITION_EX_SPECIFIC_SOURCE_REQUIRED")
        if ex != cash._day(t["candidate_ex"], "candidate_ex") or (closed_record is None and not ex <= record <= pay):
            raise ValueError("CA_EX_RECORD_PAY_CONFLICT")
        if direct_ex and cash._day(payload.get("source_declared_ex_date"), "source_declared_ex_date") != ex:
            raise ValueError("CA_DIRECT_ISSUER_EX_CONFLICT")
        # Retrospective SEC facts have no publication or actual venue authority.
        # All old public-notice scopes retain their original condition.
        if not (sec_cash or report_cash or foreign_common or (component_group and payload.get("cash_component_group_binding",{}).get("cash_evidence_role")==BASE_VARIABLE_COMPONENT_ROLE)) and publication > record-pd.Timedelta(days=10):
            raise ValueError("CA_NORMAL_CASH_ADVANCE_NOTICE_UNQUALIFIED")
        if not pd.Timestamp("2023-01-01") <= ex < pd.Timestamp("2026-01-01"):
            raise ValueError("CA_SOURCE_EVENT_OUTSIDE_RESEARCH_SCOPE")
        if reconstructed_cash:
            available=None
        else:
            available = cash._aware(t["available"], "publication_upper_bound")
            expected_available = (publication+pd.Timedelta(days=2)).tz_localize("UTC")
            capture = payload.get("archive_capture_utc")
            if capture is not None:
                capture = cash._aware(capture, "archive_capture")
                if (payload.get("archive_original_issuer_url") != payload["source_url"]
                        or capture >= pd.Timestamp("2026-01-01", tz="UTC")
                        or capture < publication.tz_localize("UTC")
                        or capture >= cash._clock(ex, 9, 30)):
                    raise ValueError("CA_PRE_EX_ORIGINAL_ISSUER_ARCHIVE_REQUIRED")
                expected_available = max(expected_available, capture)
            if available != expected_available or available >= cash._clock(ex, 9, 30):
                raise ValueError("CA_CONSERVATIVE_PUBLICATION_BOUND_REQUIRED")
        if frozen_namespace:
            identity=copy.deepcopy(frozen_namespace_identity);sid=identity["identity"]["security_id"]
        elif (report_cash or dated_unit or component_group or sec_cash or foreign_common or (post_verified and payload.get("issuer_pdf_cash_binding") is not None)) and payload.get("frozen_account_identity_binding") is not None:
            identity=copy.deepcopy(payload["frozen_account_identity_binding"])
            sid=identity["identity"]["security_id"]
        else:
            sid, identity = cash._identity(t, entry["identity_binding"], cash._clock(ex, 9, 30))
        prior = dates[dates.index(ex)-1] if dates.index(ex)>0 else None
        endpoint = entry["prior_raw_close"]
        if prior is None or endpoint["prior_date"] != str(prior.date()) or endpoint.get("raw_row_present") is not True:
            raise ValueError("CA_PRIOR_RAW_COORDINATE_MISSING")
        close = endpoint["raw_close"]
        if not isinstance(close, (int,float)) or isinstance(close,bool) or not math.isfinite(close) or close<=0 or amount/close>=.25:
            raise ValueError("CA_SMALL_ORDINARY_CASH_UNQUALIFIED")
        audit_endpoint = audit["endpoints"].get(t["ticker"]+"|"+str(ex.date()))
        if audit_endpoint != endpoint:
            raise ValueError("CA_RAW_CLOSE_AUDIT_BINDING_CHANGED")
        rows = [r for r in audit["audit_rows"] if r["ticker"] == t["ticker"] and str(r["event_date"])[:10] == str(ex.date())]
        if any(r.get("share_event") is not False or isinstance(r.get("factor_a"), bool) or not isinstance(r.get("factor_a"), (int,float)) or not math.isfinite(r["factor_a"]) or r["factor_a"] <= 0 or r.get("manual_wolf") is not False for r in rows):
            raise ValueError("CA_PARALLEL_SHARE_OR_NONCASH_CONFLICT")
        if any((e.old_ticker == t["ticker"] or e.new_ticker == t["ticker"]) and pd.Timestamp(e.effective_date) == ex for e in original_events.get("corporate_actions", ())):
            raise ValueError("CA_PARALLEL_ORIGINAL_SHARE_ACTION")
        issuer_key = (t["ticker"], str(ex.date()))
        ca = owner._frozen_ca_module
        parent_ref = entry.get("existing_parent_cash_event")
        if parent_ref is not None:
            # Evidence corroborates an immutable original cash event; never
            # constructs another event or changes its immutable source fields.
            # This descendant explicitly uses the verified ordinary cash clock.
            matches = [e for e in original if e.event_id == parent_ref.get("event_id")]
            if (reconstructed_cash or entry.get("source_verified_ordinary_parent_cash") is not True
                    or set(parent_ref) != {"event_id", "event_fingerprint"}
                    or len(matches) != 1
                    or type(matches[0]) is not ca.SourceBackedEntitlementEvent):
                raise ValueError("CA_EXACT_ORIGINAL_CASH_EVENT_REF_REQUIRED")
            event = matches[0]
            ca._validate_cash_entitlement_terms(event)
            if (event.event_fingerprint != parent_ref["event_fingerprint"]
                    or event.event_fingerprint not in bundle["parent_entitlement_event_fingerprints"]
                    or event.event_id in corroborated_parent_ids
                    or event.action_type != "CASH_DIVIDEND"
                    or event.old_security_id != sid or event.ticker != t["ticker"]
                    or event.ex_date != str(ex.date())
                    or event.record_date != str(record.date())
                    or event.pay_date != str(pay.date())
                    or event.cash_per_old_share != amount or event.currency != "USD"
                    or event.amount_unit != ca.USD_PER_RAW_OLD_SHARE
                    or event.quantity_coordinate != ca.RAW_OLD_SHARE_COORDINATE
                    or cash._aware(event.available_at, "original_available") >= cash._clock(ex, 9, 30)
                    or mappings.get(sid) != event.ticker
                    or issuer_key not in economic):
                raise ValueError("CA_ORIGINAL_CASH_CORROBORATION_SUBJECT_CONFLICT")
            corroborated_parent_ids.add(event.event_id)
        else:
            if issuer_key in economic:
                raise ValueError("CA_DUPLICATE_OR_PARALLEL_CASH_EVENT")
            economic.add(issuer_key)
            event_class=ca.ResearchClosedRecordCashEvent if closed_record is not None else ca.ResearchReconstructedCashEvent if reconstructed_cash else ca.SourceBackedEntitlementEvent
            extra=dict(reconstruction_ref=ref["path"],reconstruction_sha256=ref["sha256"],
                source_scope="B_FROZEN_PRE2026_ACCOUNTING_ONLY") if reconstructed_cash else {}
            if closed_record is not None:
                extra["closed_record_research_binding"]=copy.deepcopy(closed_record)
            event_id=("SOURCE_COMPONENT_GROUP:"+payload["cash_component_group_binding"]["group_id"] if component_group
                else "SOURCE_CASH:"+_hash(dict(security_id=sid,ex=str(ex.date()),family="CASH_DIVIDEND")))
            event = event_class(event_id,
                "CASH_DIVIDEND",sid,t["ticker"],str(ex.date()),str(record.date()),str(pay.date()),None if reconstructed_cash else str(available),float(amount),
                "USD",ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,"TIER1_ISSUER_REGULATOR_EXCHANGE",payload["source_url"],guard["sha256"],**extra)
            if reconstructed_cash:
                post_verified_entries.append(dict(event_fingerprint=event.event_fingerprint,
                    source_projection_ref=dict(ref),publication_available_at=event.available_at,
                    historical_availability_qualified=False,clock_role=event.clock_role))
            bridge_matches=[r for r in post_native_bridges if r["original_fact_ref"]==ref]
            if event.event_id in ids or (not bridge_matches and sid in mappings and mappings[sid] != event.ticker):
                raise ValueError("CA_EVENT_OR_SECURITY_MAPPING_CONFLICT")
            if not bridge_matches and any(k != sid and v == event.ticker for k,v in mappings.items()):
                raise ValueError("CA_EXISTING_SECURITY_CLASS_CONFLICT")
            ids.add(event.event_id)
            if not bridge_matches:mappings[sid] = event.ticker
            typed.append(event)
        exact = entry["original_unsupported_keys"]
        for item in exact:
            k = _key(item)
            if key_counts.get(k) != 1 or item.get("reason") != "VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY":
                raise ValueError("CA_EXACT_UNIQUE_ORIGINAL_TRANSFORM_KEY_REQUIRED")
            if item["ticker"] != event.ticker or str(cash._day(item["effective_date"],"effective").date()) != event.ex_date:
                raise ValueError("CA_EXACT_EVENT_COORDINATE_MISMATCH")
            if not rows or audit_key_counts.get(k) != 1:
                raise ValueError("CA_ORIGINAL_VENDOR_MAPPING_AUDIT_REQUIRED")
            if k in removed:
                raise ValueError("CA_DUPLICATE_REMOVAL_AUTHORITY")
            removed[k] = copy.deepcopy(item)
        historical_ex_adjudication = None
        if payload.get("source_scope") in ("FROZEN_PRE2026_NYSE_COMMON_USD", LATE_CURRENCY_SOURCE_SCOPE, SEC_CASH_SOURCE_SCOPE, REPORT_CASH_SOURCE_SCOPE, DATED_COMMON_UNIT_SOURCE_SCOPE, COMPONENT_GROUP_SOURCE_SCOPE, FOREIGN_COMMON_SOURCE_SCOPE):
            facts = payload["historical_ex_adjudication_input"]
            expected = dict(ticker=event.ticker, security_id=sid,
                security_type="COMMON_STOCK", listing_identity=t["listing"],
                currency="USD", cash_per_raw_share=amount,
                record_date=str(record.date()), pay_date=str(pay.date()),
                publication_calendar_date=None if report_cash else str(publication.date()))
            if any(facts.get(k) != v for k,v in expected.items()):
                raise ValueError("CA_HISTORICAL_ADJUDICATION_SUBJECT_CHANGED")
            if (facts.get("exact_frozen_event_key") not in exact
                    or len(exact) != 1
                    or facts.get("frozen_event_exact_row_count") != 1):
                raise ValueError("CA_HISTORICAL_EXACT_EVENT_BINDING_REQUIRED")
            price = facts.get("prior_raw_close", {})
            if (price.get("raw_close") != close
                    or price.get("trade_date") != endpoint["prior_date"]):
                raise ValueError("CA_HISTORICAL_RAW_ENDPOINT_CHANGED")
            envelope = dict(payload=facts, **ref, guard=dict(
                status="HASH_VERIFIED_PAYLOAD", **ref, payload_sha256=_hash(facts)))
            historical_ex_adjudication = cash.adjudicate_post_verified_cash_ex(
                envelope, calendar=[str(d.date()) for d in dates],
                calendar_binding=bundle["historical_calendar_binding"],
                rule_sources=bundle["historical_rule_sources"],
                scope_end_exclusive="2026-01-01", source_scope=payload["source_scope"])
            expected_status = "QUALIFIED_RESEARCH_FROZEN_CASH_FACT" if (sec_cash or report_cash or dated_unit or component_group or foreign_common) else "ADJUDICATED_RESEARCH_EX_DATE"
            if (historical_ex_adjudication["status"] != expected_status
                    or historical_ex_adjudication["ex_date"] != event.ex_date):
                raise ValueError("CA_HISTORICAL_EX_ADJUDICATION_BLOCKED:" + str(historical_ex_adjudication.get("reason")))
        proofs.append(dict(event_fingerprint=event.event_fingerprint,issuer_pay_date=event.pay_date,
            research_cash_not_before_date=str((pay+pd.Timedelta(days=1)).date()),
            source_fact_ref=ref,identity=identity,ex_rule=rule_key,ex_status=("RESEARCH_SOURCE_DECLARED_EX_WITH_LITERAL_RECORD_AND_UNCHANGED_FROZEN_CALENDAR"
                if source_ex_policy else "RESEARCH_NORMAL_SMALL_CASH_DERIVED_FROM_RECORD_AND_FROZEN_CALENDAR"),
            source_ex_directly_declared=direct_ex,source_declared_ex_date=str(ex.date()) if direct_ex else None,
            original_exact_keys=exact,parallel_rows_checked=len(rows),
            vendor_affine_cash_inferred=False,vendor_ratio_status="PRESERVED_UNRECONCILED_PRICE_TRANSFORM_NOT_SHARE_OR_CASH_AUTHORITY",publication_upper_bound=event.available_at,
            historical_exchange_received_at="UNKNOWN",historical_broker_received_at="UNKNOWN"))
        if t["security_type"] == "AMERICAN_DEPOSITARY_SHARE":
            proofs[-1].update(
                ads_unit_evidence=copy.deepcopy(guarded["ads_unit_evidence"]),
                cash_deductions=copy.deepcopy(guarded.get("cash_deductions", {})),
                gross_cash_basis="ANNOUNCED_PER_RAW_ADS_BEFORE_DEDUCTIONS; NO_FEE_OR_WITHHOLDING_ESTIMATE",
                broker_payment="NOT_OBSERVED")
        if parent_ref is not None:
            proofs[-1].update(event_binding_role="EXACT_PARENT_CASH_CORROBORATION_NO_NEW_EVENT",
                original_typed_event_ref=dict(parent_ref),original_source_reference=event.source_reference,
                original_source_fingerprint=event.source_fingerprint,
                original_available_at=event.available_at,new_source_publication_bound=str(available),
                original_typed_fields_and_fingerprint_preserved=True,
                original_frozen_classification_unchanged=True,
                descendant_ordinary_cash_clock= CLOCK,
                descendant_clock_is_new_source_account_identity=True)
        if post_verified:
            if payload.get("issuer_pdf_cash_binding") is not None:
                proofs[-1].update(clock_role=event.clock_role,historical_availability_qualified=False,
                    issuer_pdf_cash_binding=copy.deepcopy(payload["issuer_pdf_cash_binding"]),
                    source_transport_profile=ISSUER_PDF_PROFILE,actual_exchange_ex_authority="UNKNOWN",
                    exchange_notice_authority="UNKNOWN",historical_availability_authority="UNKNOWN",
                    source_projection_payload_sha256=_hash(original_payload))
            else:
                proofs[-1].update(clock_role=event.clock_role,historical_availability_qualified=False,
                    actual_late_archive_capture_utc=payload["actual_late_archive_capture_utc"],
                    original_record_literal_preserved=payload["original_record_literal_preserved"],
                    source_projection_payload_sha256=_hash(original_payload))
        if late_currency:
            proofs[-1].update(clock_role=event.clock_role,historical_availability_qualified=False,
                currency_evidence_role=LATE_CURRENCY_ROLE,
                late_currency_binding=copy.deepcopy(payload["late_currency_binding"]),
                source_projection_payload_sha256=_hash(original_payload))
        if foreign_common:
            proofs[-1].update(clock_role=event.clock_role,historical_availability_qualified=False,cash_evidence_role=FOREIGN_COMMON_ROLE,
                ex_status="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
                foreign_same_file_explicit_usd_binding=copy.deepcopy(payload["foreign_same_file_explicit_usd_binding"]),source_projection_payload_sha256=_hash(original_payload))
        if sec_cash:
            proofs[-1].update(clock_role=event.clock_role,historical_availability_qualified=False,
                cash_evidence_role=SEC_CASH_ROLE,
                ex_status="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
                exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
                sec_frozen_cash_binding=copy.deepcopy(payload["sec_frozen_cash_binding"]),
                source_projection_payload_sha256=_hash(original_payload))
        if report_cash:
            proofs[-1].update(clock_role=event.clock_role,historical_availability_qualified=False,
                cash_evidence_role=REPORT_CASH_ROLE,ex_status="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
                exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
                report_frozen_cash_binding=copy.deepcopy(payload["report_frozen_cash_binding"]),
                source_projection_payload_sha256=_hash(original_payload))
        if dated_unit:
            proofs[-1].update(clock_role=event.clock_role,historical_availability_qualified=False,
                cash_evidence_role=DATED_COMMON_UNIT_ROLE,ex_status="EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY",
                exchange_notice_authority="UNKNOWN",actual_exchange_ex_authority="UNKNOWN",
                dated_common_unit_bridge_binding=copy.deepcopy(payload["dated_common_unit_bridge_binding"]),
                source_projection_payload_sha256=_hash(original_payload))
        if nyse_post_t1_binding is not None:
            proofs[-1]["nyse_post_t1_nonbusiness_record_binding"]=copy.deepcopy(nyse_post_t1_binding)
        if frozen_namespace:
            proofs[-1].update(frozen_common_cash_namespace_binding=copy.deepcopy(frozen_namespace_binding),
                historical_availability_qualified=False,clock_role=event.clock_role,
                source_projection_payload_sha256=_hash(original_payload))
        if component_group:
            proofs[-1].update(cash_component_group_binding=copy.deepcopy(payload["cash_component_group_binding"]),
                source_projection_payload_sha256=_hash(original_payload),
                cash_clock_consumption_set_role=COMPONENT_GROUP_SCOPE["consumption_set_role"],
                source_cash_classification=("EXPLICIT_TOTAL_BASE_AND_VARIABLE_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION" if payload["cash_component_group_binding"]["cash_evidence_role"]==BASE_VARIABLE_COMPONENT_ROLE else "ANNUAL_AND_QUARTERLY_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION"))
        if closed_record is not None:
            proofs[-1].update(ex_status=cash.CLOSED_RECORD_RESEARCH_ROLE,
                closed_record_research_binding=copy.deepcopy(closed_record),
                prior_entitlement_session=closed_record["prior_entitlement_session"],
                next_spendable_session=closed_record["next_spendable_session"],
                entitlement_reconstruction_role=closed_record["entitlement_reconstruction_role"],
                original_record_date_preserved=True,actual_exchange_ex_authority="UNKNOWN",
                clearing_delivery_day_authority="UNKNOWN",historical_availability_authority="UNKNOWN")
        if historical_ex_adjudication is not None:
            proofs[-1]["historical_ex_adjudication"] = historical_ex_adjudication
        bridge_matches=[r for r in post_native_bridges if r["original_fact_ref"]==ref]
        if bridge_matches:
            if len(bridge_matches)!=1 or parent_ref is not None:
                raise ValueError("CA_POST_NATIVE_UNIQUE_ADDED_CASH_EVENT_REQUIRED")
            old_fp=event.event_fingerprint;old_id=event.event_id
            index=bridge_matches[0].get("native_proof_index")
            if type(index) is not int or not 0<=index<len(post_native_proofs):
                raise ValueError("CA_POST_NATIVE_EXACT_PROOF_INDEX_REQUIRED")
            projected,bridge_proof=_post_native_cash_raw_namespace(owner,event,entry,identity,bridge_matches[0],native_proof=post_native_proofs[index])
            bridge_proof.update(bridge_packet_ref=copy.deepcopy(bridge_ref),original_native_proof_ref=copy.deepcopy(old_proof_ref),native_proof_index=index)
            raw_sid=projected.old_security_id
            if projected.event_id in ids or (raw_sid in mappings and mappings[raw_sid]!=projected.ticker):
                raise ValueError("CA_POST_NATIVE_RAW_MAPPING_CONFLICT")
            typed[typed.index(event)]=projected
            if sid in mappings and not any(e.old_security_id==sid for e in typed):del mappings[sid]
            if any(k!=raw_sid and v==projected.ticker for k,v in mappings.items()):
                raise ValueError("CA_POST_NATIVE_REMAINING_SECURITY_CLASS_CONFLICT")
            ids.remove(old_id);ids.add(projected.event_id);mappings[raw_sid]=projected.ticker
            for post in post_verified_entries:
                if post["event_fingerprint"]==old_fp:post["event_fingerprint"]=projected.event_fingerprint
            proofs[-1].update(event_fingerprint=projected.event_fingerprint,post_native_dated_raw_namespace_projection=bridge_proof)
            event=projected

    typed.sort(key=lambda e:(str(getattr(e,"ex_date",getattr(e,"effective_at",""))),e.event_id))
    classified = classify_existing_cash(original_events)
    if bundle["existing_cash_classification"] != classified:
        raise ValueError("CA_EXISTING_CLOCK_CLASSIFICATION_CHANGED")
    old_ordinary = {item["event_fingerprint"] for item in classified
                    if item["status"] == "SOURCE_CLASS_VERIFIED_ORDINARY"}
    ordinary = frozenset(old_ordinary | {e.event_fingerprint for e in typed if (e.event_fingerprint not in bundle["parent_entitlement_event_fingerprints"] or e.event_id in corroborated_parent_ids) and e.action_type == "CASH_DIVIDEND" and e.ticker != "MKFG"})
    source_manifest = dict(schema=SCHEMA,source_version_id=bundle["source_version_id"],parent_source_binding=original_events.get("entitlement_source_binding"),
        proofs=proofs,removed_exact_original_keys=list(removed.values()),clock=CLOCK,existing_cash_classification=classified,
        authority="RESEARCH_SOURCE_ACCOUNT_DESCENDANT; NO_HISTORICAL_PIT_OR_BROKER_CERTIFICATION")
    if frozen_namespace_scope_enabled:
        source_manifest["frozen_common_cash_namespace_scope"]=copy.deepcopy(FROZEN_COMMON_NAMESPACE_SCOPE)
    if component_group_scope_enabled:
        source_manifest.update(same_clock_common_cash_component_group_scope=copy.deepcopy(COMPONENT_GROUP_SCOPE),
            cash_clock_consumption_set_role=COMPONENT_GROUP_SCOPE["consumption_set_role"])
    if base_variable_component_scope_enabled:
        source_manifest.update(base_variable_common_cash_component_group_scope=copy.deepcopy(BASE_VARIABLE_COMPONENT_SCOPE),
            cash_clock_consumption_set_role=BASE_VARIABLE_COMPONENT_SCOPE["consumption_set_role"])
    if closed_record_scope_enabled:
        source_manifest["closed_record_next_session_research_scope"]=copy.deepcopy(CLOSED_RECORD_RESEARCH_SCOPE)
    if late_currency_scope_enabled:
        source_manifest["later_same_event_currency_cash_scope"] = copy.deepcopy(LATE_CURRENCY_SCOPE)
    if foreign_common_scope_enabled:
        source_manifest["foreign_nasdaq_ordinary_same_file_explicit_usd_scope"]=copy.deepcopy(FOREIGN_COMMON_SCOPE)
    if sec_cash_scope_enabled:
        source_manifest["sec_same_file_cash_fact_scope"] = copy.deepcopy(SEC_CASH_SCOPE)
    if sec_html_scope_enabled:
        source_manifest["sec_primary_html_frozen_common_cash_scope"]=copy.deepcopy(SEC_PRIMARY_HTML_SCOPE)
    if issuer_pdf_scope_enabled:
        source_manifest["issuer_pdf_frozen_common_cash_scope"]=copy.deepcopy(ISSUER_PDF_SCOPE)
    if dated_unit_scope_enabled:
        source_manifest["dated_notice_frozen_common_unit_scope"]=copy.deepcopy(DATED_COMMON_UNIT_SCOPE)
    if sec_submission_scope_enabled:source_manifest["sec_static_submission_common_cash_scope"]=copy.deepcopy(SEC_STATIC_SUBMISSION_SCOPE)
    if sec_primary_body_scope_enabled:source_manifest["sec_static_primary_body_common_cash_scope"]=copy.deepcopy(SEC_STATIC_PRIMARY_BODY_SCOPE)
    if post_native_raw_scope_enabled:source_manifest["post_native_dated_raw_cash_namespace_scope"]=copy.deepcopy(POST_NATIVE_DATED_RAW_CASH_SCOPE)
    if report_cash_scope_enabled:
        source_manifest["report_same_file_cash_table_scope"]=copy.deepcopy(REPORT_CASH_SCOPE)
    if nyse_post_t1_scope is not None:
        source_manifest["nyse_post_t1_nonbusiness_record_scope"]=copy.deepcopy(nyse_post_t1_scope)
    if bundle.get("cns_bank_holiday_record_policy") is not None:
        source_manifest["cns_bank_holiday_record_policy"]=bundle["cns_bank_holiday_record_policy"]
    if nyse_nonbusiness_scope is not None:
        source_manifest["report_nyse_pre_t1_nonbusiness_record_scope"]=copy.deepcopy(nyse_nonbusiness_scope)
    if ads_scope_enabled:
        source_manifest["source_declared_ads_cash_scope"] = copy.deepcopy(SOURCE_DECLARED_ADS_CASH_SCOPE)
    if direct_ex_scope_enabled:
        source_manifest["source_declared_cash_ex_scope"] = copy.deepcopy(SOURCE_DECLARED_CASH_EX_SCOPE)
    if corroborated_parent_ids:
        source_manifest["parent_ordinary_cash_corroborations"] = [dict(
            event_fingerprint=p["event_fingerprint"], original_typed_event_ref=p["original_typed_event_ref"],
            source_fact_ref=p["source_fact_ref"], original_classification=next(
                c for c in classified if c["event_fingerprint"]==p["event_fingerprint"]),
            descendant_clock=CLOCK, original_typed_and_frozen_classification_unchanged=True,
            new_source_account_identity_not_old_account_equivalence=True)
            for p in proofs if p.get("event_binding_role")=="EXACT_PARENT_CASH_CORROBORATION_NO_NEW_EVENT"]
    result = dict(original_events)
    result.update(entitlement_events=tuple(typed),entitlement_security_tickers=mappings,
        unsupported_events=tuple(e for e in unsupported if _key(e) not in removed),
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",source_fingerprint=_hash(source_manifest),
            quantity_coordinate=owner._frozen_ca_module.RAW_OLD_SHARE_COORDINATE,
            event_fingerprints=[e.event_fingerprint for e in typed],security_tickers=mappings,manifest=source_manifest))
    if post_verified_entries:
        parent_authority=original_events.get("research_account_authority")
        if parent_authority is not None:
            raise ValueError("CA_ORIGINAL_B_SOURCE_MUST_NOT_HAVE_A_OR_CASH_AUTHORITY")
        admission=dict(POST_VERIFIED_SCOPE,schema="B_FROZEN_HISTORY_POST_VERIFIED_CASH_ADMISSION_V1",
            source_contract_ref=dict(bundle_ref),source_binding_fingerprint=result["entitlement_source_binding"]["source_fingerprint"],
            events=post_verified_entries)
        result["research_account_authority"]=dict(schema="B_FROZEN_HISTORY_CASH_ACCOUNT_AUTHORITY_V1",
            scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",task_id="V24_B_FAST_TRACK_PAIR_COMPLETION_R1",
            clock_role="POST_VERIFIED_ACCOUNTING_ONLY",strict_PIT_promotion_eligible=False,
            production_qualified=False,frozen_history_cash_admission=admission)
        owner._frozen_ca_module._validate_research_account_authority(tuple(typed),result["research_account_authority"])
    receipt = dict(source_version_id=bundle["source_version_id"],added_events=len(typed)-len(original),parent_events=len(original),
        removed_keys=len(removed),remaining_unsupported=len(result["unsupported_events"]),proofs=proofs,
        corroborated_parent_cash_events=len(corroborated_parent_ids),
        source_binding_fingerprint=result["entitlement_source_binding"]["source_fingerprint"],
        old_event_bytes_unchanged=all(asdict(e)==asdict(next(x for x in typed if x.event_id==e.event_id)) for e in original),
        ordinary_cash_clock_fingerprints=sorted(ordinary),existing_cash_classification=classified,decision_quality_modified=False,broker_payment_proven=False)
    if frozen_namespace_scope_enabled:
        receipt["frozen_common_cash_namespace_scope"]=copy.deepcopy(FROZEN_COMMON_NAMESPACE_SCOPE)
    if closed_record_scope_enabled:
        receipt["closed_record_next_session_research_scope"]=copy.deepcopy(CLOSED_RECORD_RESEARCH_SCOPE)
    if component_group_scope_enabled:
        receipt.update(same_clock_common_cash_component_group_scope=copy.deepcopy(COMPONENT_GROUP_SCOPE),
            cash_clock_consumption_set_role=COMPONENT_GROUP_SCOPE["consumption_set_role"],
            component_group_clock_fingerprints=[p["event_fingerprint"] for p in proofs if p.get("cash_component_group_binding",{}).get("cash_evidence_role")==COMPONENT_GROUP_ROLE])
    if base_variable_component_scope_enabled:
        receipt.update(base_variable_common_cash_component_group_scope=copy.deepcopy(BASE_VARIABLE_COMPONENT_SCOPE),
            cash_clock_consumption_set_role=BASE_VARIABLE_COMPONENT_SCOPE["consumption_set_role"],
            base_variable_component_group_clock_fingerprints=[p["event_fingerprint"] for p in proofs if p.get("cash_component_group_binding",{}).get("cash_evidence_role")==BASE_VARIABLE_COMPONENT_ROLE])
    if late_currency_scope_enabled:
        receipt["later_same_event_currency_cash_scope"] = copy.deepcopy(LATE_CURRENCY_SCOPE)
    if foreign_common_scope_enabled:
        receipt["foreign_nasdaq_ordinary_same_file_explicit_usd_scope"]=copy.deepcopy(FOREIGN_COMMON_SCOPE)
    if sec_cash_scope_enabled:
        receipt["sec_same_file_cash_fact_scope"] = copy.deepcopy(SEC_CASH_SCOPE)
    if sec_html_scope_enabled:
        receipt["sec_primary_html_frozen_common_cash_scope"]=copy.deepcopy(SEC_PRIMARY_HTML_SCOPE)
    if dated_unit_scope_enabled:
        receipt["dated_notice_frozen_common_unit_scope"]=copy.deepcopy(DATED_COMMON_UNIT_SCOPE)
    if sec_submission_scope_enabled:receipt["sec_static_submission_common_cash_scope"]=copy.deepcopy(SEC_STATIC_SUBMISSION_SCOPE)
    if sec_primary_body_scope_enabled:receipt["sec_static_primary_body_common_cash_scope"]=copy.deepcopy(SEC_STATIC_PRIMARY_BODY_SCOPE)
    if post_native_raw_scope_enabled:receipt["post_native_dated_raw_cash_namespace_scope"]=copy.deepcopy(POST_NATIVE_DATED_RAW_CASH_SCOPE)
    if report_cash_scope_enabled:
        receipt["report_same_file_cash_table_scope"]=copy.deepcopy(REPORT_CASH_SCOPE)
    if nyse_post_t1_scope is not None:
        receipt["nyse_post_t1_nonbusiness_record_scope"]=copy.deepcopy(nyse_post_t1_scope)
    if bundle.get("cns_bank_holiday_record_policy") is not None:
        receipt["cns_bank_holiday_record_policy"]=bundle["cns_bank_holiday_record_policy"]
    if nyse_nonbusiness_scope is not None:
        receipt["report_nyse_pre_t1_nonbusiness_record_scope"]=copy.deepcopy(nyse_nonbusiness_scope)
    if ads_scope_enabled:
        receipt["source_declared_ads_cash_scope"] = copy.deepcopy(SOURCE_DECLARED_ADS_CASH_SCOPE)
    if direct_ex_scope_enabled:
        receipt["source_declared_cash_ex_scope"] = copy.deepcopy(SOURCE_DECLARED_CASH_EX_SCOPE)
    return dict(events=result,receipt=receipt,ordinary_cash_event_fingerprints=ordinary)
