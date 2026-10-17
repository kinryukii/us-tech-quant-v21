"""Synthetic source-contract counterexamples; no real source/risk/account reads."""
from dataclasses import asdict
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import copy
import hashlib
import json
import pandas as pd
import pytest
from scripts.research.a2.data import reused_pair_ca_sources as mod
from scripts.research.a2.data import joint_cash_bindings as cash
from scripts.v22 import corporate_action_transition_r1 as ca


class Harness:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp_path, self.files, self.sequence = tmp_path, {}, 0
        harness = self
        class VirtualDPath:
            def __init__(self, value):
                self.key = str(value)
                self.drive = PureWindowsPath(self.key).drive
            def open(self, *args, **kwargs):
                return harness.files[self.key].open(*args, **kwargs)
            def read_text(self, *args, **kwargs):
                return harness.files[self.key].read_text(*args, **kwargs)
            def __str__(self):
                return self.key
        monkeypatch.setattr(mod, "Path", VirtualDPath)
        # Deliberately synthetic752-session axis: no market calendar is loaded.
        dates = list(pd.bdate_range("2023-01-03", "2025-12-31"))
        dates.remove(pd.Timestamp("2024-05-27"))
        remove = len(dates)-752
        dates = [d for i,d in enumerate(dates) if not (500 <= i < 500+remove)]
        assert len(dates) == 752
        self.dates = tuple(dates)
        self.owner = SimpleNamespace(_frozen_ca_module=ca)
        self.vendor = dict(ticker="AAA", effective_date="2023-01-19",
                           reason="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY",
                           source_fingerprint="a"*64, factor_a=.99, factor_b=0.)
        self.raw_flag = dict(self.vendor, reason="RAW_LARGE_MOVE")
        self.original = dict(entitlement_events=(), corporate_actions=(),
            unsupported_events=(self.vendor,self.raw_flag),
            entitlement_security_tickers={},
            entitlement_source_binding=dict(status="FAKE_ONLY",manifest=dict(proofs=[])))
        self.payload = dict(id="FAKE_AAA_2023Q1",issuer="FAKE Issuer",listing_identity="NYSE:AAA",
            security_type="COMMON_STOCK",cash_per_common_share=2.,
            cash_is_gross_announced_amount=True,currency="USD",currency_basis="EXPLICIT_USD",
            record_date="2023-01-20",pay_date="2023-02-01",publication_date="2022-12-01",
            candidate_ex_date="2023-01-19",availability_bound=dict(available_at="2022-12-03T00:00:00Z"),
            ordinary_cash_dividend=True,source_url="https://issuer.example/FAKE_2022_notice")
        self.endpoint = dict(prior_date="2023-01-18",raw_row_present=True,raw_close=100.)
        self.entry = dict(fact_ref=self.write(self.payload),
            identity_binding=self.identity("AAA"),prior_raw_close=self.endpoint,
            original_unsupported_keys=[self.vendor])
        self.audit = dict(calendar=[str(d.date()) for d in self.dates],
            endpoints={"AAA|2023-01-19":self.endpoint},
            audit_rows=[dict(ticker="AAA",event_date="2023-01-19",share_event=False,
                             factor_a=.99,factor_b=0.,manual_wolf=False)],
            source_events=[self.vendor])
        self.bundle = dict(schema=mod.SCHEMA,status="FROZEN",clock_convention=mod.CLOCK,
            historical_broker_payment_proven=False,source_version_id="FAKE_ONLY_V1",
            source_refs=[self.write(dict(source="FAKE historical issuer bytes"))],
            parent_cash_kwargs_ref=self.write(dict(parent="FAKE_ONLY")),
            local_identity_audit_ref=self.write(self.audit),
            parent_entitlement_event_fingerprints=[],events=[self.entry],existing_cash_classification=[])
    def identity(self, ticker, issuer="FAKE Issuer"):
        body=dict(security_id=cash.source_derived_security_id(issuer,ticker,"NYSE:"+ticker),
                  identity_kind="SOURCE_DERIVED_ISSUER_COMMON_CLASS",issuer=issuer,ticker=ticker,
                  listing_identity="NYSE:"+ticker,security_type="COMMON_STOCK")
        return dict(body,identity_payload_sha256=mod._hash(body),source_reference="https://issuer.example/FAKE_identity",
                    source_fingerprint="f"*64,available_at="2022-12-03T00:00:00Z")
    def write(self, value):
        self.sequence += 1
        raw=json.dumps(value,sort_keys=True,ensure_ascii=False).encode()
        key=f"D:/FAKE_ONLY/source_{self.sequence}.json"
        target=self.tmp_path/f"source_{self.sequence}.json";target.write_bytes(raw)
        self.files[key]=target
        return dict(path=key,sha256=hashlib.sha256(raw).hexdigest())
    def payload_update(self, **changes):
        self.payload.update(changes);self.entry["fact_ref"]=self.write(self.payload)
    def audit_update(self):
        self.bundle["local_identity_audit_ref"]=self.write(self.audit)
    def bind(self):
        return mod.bind_source_account_descendant(self.owner,self.original,self.bundle,account_dates=self.dates)
    def add_original(self, title="Quarterly cash dividend", *, precedence=False, ticker="OLD"):
        identity=self.identity(ticker,issuer="FAKE Old Issuer")
        event=ca.SourceBackedEntitlementEvent("FAKE_OLD", "CASH_DIVIDEND",identity["security_id"],ticker,
            "2023-02-01","2023-02-02","2023-03-01","2022-12-03T00:00:00Z",1.,"USD",
            ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,
            "TIER1_ISSUER_REGULATOR_EXCHANGE","https://issuer.example/FAKE_old","c"*64)
        evidence=self.write(dict(title=title))
        normalized=dict(original_source_projection=evidence)
        if precedence:
            # Invalid external body is intentional: classification must not open it.
            normalized["source_precedence_fact"]=dict(path="E:/FORBIDDEN",sha256="0"*64)
        norm_ref=self.write(normalized)
        self.original["entitlement_events"]=(event,)
        self.original["entitlement_security_tickers"]={event.old_security_id:ticker}
        self.original["entitlement_source_binding"]["manifest"]["proofs"]=[dict(event_fingerprint=event.event_fingerprint,projection=norm_ref)]
        self.bundle["parent_entitlement_event_fingerprints"]=[event.event_fingerprint]
        self.bundle["existing_cash_classification"]=mod.classify_existing_cash(self.original)
        return event,evidence,norm_ref


@pytest.fixture
def h(tmp_path,monkeypatch):
    return Harness(tmp_path,monkeypatch)


def test_exact_removal_preserves_originals_other_flags_and_issuer_amount(h):
    before=copy.deepcopy(h.original)
    result=h.bind();event=result["events"]["entitlement_events"][0]
    assert event.cash_per_old_share==2.
    assert event.pay_date=="2023-02-01"
    assert result["receipt"]["proofs"][0]["research_cash_not_before_date"]=="2023-02-02"
    assert result["events"]["unsupported_events"]==(h.raw_flag,)
    assert h.original==before
    assert result["receipt"]["proofs"][0]["vendor_affine_cash_inferred"] is False
    assert "UNRECONCILED" in result["receipt"]["proofs"][0]["vendor_ratio_status"]
    assert event.event_fingerprint in result["ordinary_cash_event_fingerprints"]


def test_price_transform_never_becomes_cash_or_raw_share_multiplier(h):
    h.audit["audit_rows"][0].update(factor_a=.4,factor_b=87.)
    h.audit_update()
    event=h.bind()["events"]["entitlement_events"][0]
    assert event.cash_per_old_share==2.
    assert event.amount_unit==ca.USD_PER_RAW_OLD_SHARE


def test_unflagged_issuer_event_is_retained_without_removal(h):
    h.entry["original_unsupported_keys"]=[]
    h.audit["audit_rows"]=[];h.audit["source_events"]=[];h.audit_update()
    result=h.bind()
    assert result["receipt"]["added_events"]==1 and result["receipt"]["removed_keys"]==0
    assert result["events"]["unsupported_events"]==h.original["unsupported_events"]


def test_future_catalogue_append_does_not_change_earlier_typed_terms(h):
    earlier=h.bind()["events"]["entitlement_events"][0]
    future=copy.deepcopy(h.entry)
    payload=dict(h.payload,id="FAKE_2024Q1",record_date="2024-01-19",pay_date="2024-02-01",
        publication_date="2023-12-01",candidate_ex_date="2024-01-18",
        availability_bound=dict(available_at="2023-12-03T00:00:00Z"))
    future.update(fact_ref=h.write(payload),original_unsupported_keys=[],
        prior_raw_close=dict(prior_date="2024-01-17",raw_row_present=True,raw_close=101.))
    h.audit["endpoints"]["AAA|2024-01-18"]=future["prior_raw_close"]
    h.audit_update();h.bundle["events"].append(future);h.bundle["source_version_id"]="FAKE_ONLY_V2"
    bound=h.bind()["events"]["entitlement_events"]
    assert asdict(earlier)==asdict(next(e for e in bound if e.ex_date==earlier.ex_date))


@pytest.mark.parametrize("which",["fact","source","parent","audit"])
def test_physical_source_sha_rechecked(h,which):
    ref={"fact":h.entry["fact_ref"],"source":h.bundle["source_refs"][0],
         "parent":h.bundle["parent_cash_kwargs_ref"],"audit":h.bundle["local_identity_audit_ref"]}[which]
    h.files[ref["path"]].write_text("CHANGED",encoding="utf-8")
    with pytest.raises(ValueError,match="PHYSICAL_BYTES_CHANGED"):
        h.bind()


@pytest.mark.parametrize("path",["E:/FORBIDDEN","F:/FORBIDDEN","C:/UNAPPROVED"])
def test_disallowed_root_rejected_before_any_file_read(h,path):
    with pytest.raises(ValueError,match="OUTSIDE_APPROVED_D_ROOT"):
        mod._pin(dict(path=path,sha256="a"*64))


@pytest.mark.parametrize("mutation",["extra_field","wrong_reason","duplicate_original","duplicate_audit","duplicate_removal"])
def test_removal_requires_full_unique_original_and_audit_key(h,mutation):
    if mutation=="extra_field": h.entry["original_unsupported_keys"]=[dict(h.vendor,unbound_extra=True)]
    elif mutation=="wrong_reason": h.entry["original_unsupported_keys"]=[h.raw_flag]
    elif mutation=="duplicate_original": h.original["unsupported_events"]+=(copy.deepcopy(h.vendor),)
    elif mutation=="duplicate_audit": h.audit["source_events"].append(copy.deepcopy(h.vendor));h.audit_update()
    else: h.entry["original_unsupported_keys"].append(copy.deepcopy(h.vendor))
    with pytest.raises(ValueError): h.bind()


@pytest.mark.parametrize("field,value",[("share_event",True),("manual_wolf",True),("factor_a",0.),
    ("factor_a",float("nan")),("factor_a",True),("factor_a",None)])
def test_same_day_share_or_unqualified_coordinate_blocks(h,field,value):
    h.audit["audit_rows"][0][field]=value;h.audit_update()
    with pytest.raises(ValueError,match="PARALLEL_SHARE_OR_NONCASH"):
        h.bind()


def test_other_same_day_audit_row_cannot_be_hidden(h):
    h.audit["audit_rows"].append(dict(h.audit["audit_rows"][0],share_event=True));h.audit_update()
    with pytest.raises(ValueError,match="PARALLEL_SHARE_OR_NONCASH"):h.bind()


def test_existing_declared_share_action_conflicts(h):
    h.original["corporate_actions"]=(SimpleNamespace(old_ticker="AAA",new_ticker="BBB",effective_date="2023-01-19"),)
    with pytest.raises(ValueError,match="PARALLEL_ORIGINAL_SHARE_ACTION"):h.bind()


@pytest.mark.parametrize("value",[True,0.,-1.,float("nan"),float("inf"),25.])
def test_invalid_or_large_issuer_cash_is_not_admitted(h,value):
    h.payload_update(cash_per_common_share=value)
    with pytest.raises(ValueError):h.bind()


@pytest.mark.parametrize("changes",[dict(ordinary_cash_dividend=False),dict(currency="EUR"),
    dict(source_url="FAKE_NOT_AN_ISSUER_URL"),dict(candidate_ex_date="2023-01-18"),
    dict(pay_date="2023-01-18"),dict(availability_bound=dict(available_at=None)),
    dict(availability_bound=dict(available_at="2022-12-02T00:00:00Z"))])
def test_fake_or_unqualified_terms_rejected(h,changes):
    h.payload_update(**changes)
    with pytest.raises((ValueError,TypeError)):h.bind()


def test_late_announcement_cannot_use_normal_ex_rule(h):
    h.payload_update(publication_date="2023-01-17",availability_bound=dict(available_at="2023-01-19T00:00:00Z"))
    with pytest.raises(ValueError,match="ADVANCE_NOTICE_UNQUALIFIED"):h.bind()


def test_mkfg_cannot_enter_new_ordinary_cash_source(h):
    h.payload_update(listing_identity="NYSE:MKFG")
    with pytest.raises(ValueError,match="MKFG_TERMINAL_SOURCE_EXCLUDED"):h.bind()


def test_truthy_unverified_transition_ref_cannot_authorize_may28(h):
    h.payload_update(record_date="2024-05-28",candidate_ex_date="2024-05-24",pay_date="2024-06-20")
    h.bundle["nyse_transition_source_ref"]={"fabricated":True}
    with pytest.raises(ValueError,match="TRANSITION_EX_SPECIFIC_SOURCE"):h.bind()


def test_raw_endpoint_must_match_pinned_audit(h):
    h.entry["prior_raw_close"]=dict(h.endpoint,raw_close=101.)
    with pytest.raises(ValueError,match="RAW_CLOSE_AUDIT_BINDING_CHANGED"):h.bind()


def test_identity_cannot_substitute_issuer_or_security(h):
    h.entry["identity_binding"]["issuer"]="OTHER Issuer"
    with pytest.raises(ValueError):h.bind()


def test_duplicate_cash_event_cannot_double_create_receivable(h):
    h.bundle["events"].append(copy.deepcopy(h.entry))
    with pytest.raises(ValueError,match="DUPLICATE_OR_PARALLEL_CASH_EVENT"):h.bind()


def test_empty_new_batch_still_rejects_duplicate_calendar(h):
    h.bundle["events"]=[]
    dates=list(h.dates);dates[5]=dates[4];h.dates=tuple(dates)
    h.audit["calendar"]=[str(d.date()) for d in h.dates];h.audit_update()
    with pytest.raises(ValueError,match="CALENDAR_UNIQUE_SORTED"):h.bind()


@pytest.mark.parametrize("title,ordinary",[("Quarterly dividend",True),("Regular cash dividend",True),
    ("Irregular payment",False),("Quarterly SPECIAL dividend",False),("Liquidating quarterly distribution",False),
    ("Merger regular payment",False),("Cash dividend",False),(None,False)])
def test_old_cash_classification_comes_from_original_source_words(h,title,ordinary):
    event,_,_=h.add_original(title)
    rows=mod.classify_existing_cash(h.original)
    assert (rows[0]["status"]=="SOURCE_CLASS_VERIFIED_ORDINARY")==ordinary
    result=h.bind()
    assert (event.event_fingerprint in result["ordinary_cash_event_fingerprints"])==ordinary
    assert asdict(event)==asdict(next(e for e in result["events"]["entitlement_events"] if e.event_id==event.event_id))


def test_caller_cannot_hide_proven_regular_event_with_legacy_label(h):
    h.add_original("Regular cash dividend")
    h.bundle["existing_cash_classification"][0]["status"]="LEGACY_NOT_RECLASSIFIED"
    with pytest.raises(ValueError,match="CLOCK_CLASSIFICATION_CHANGED"):h.bind()


def test_caller_cannot_fake_quarterly_evidence_text(h):
    h.add_original("Cash dividend")
    h.bundle["existing_cash_classification"][0].update(status="SOURCE_CLASS_VERIFIED_ORDINARY",evidence_text="Quarterly dividend")
    with pytest.raises(ValueError,match="CLOCK_CLASSIFICATION_CHANGED"):h.bind()


def test_precedence_stays_legacy_without_opening_body(h):
    event,_,_=h.add_original("Quarterly dividend",precedence=True)
    rows=mod.classify_existing_cash(h.original)
    assert rows[0]["reason"]=="SOURCE_PRECEDENCE_PRESERVED_UNRECLASSIFIED"
    assert event.event_fingerprint not in h.bind()["ordinary_cash_event_fingerprints"]


def test_old_original_projection_bytes_rechecked(h):
    _,evidence,_=h.add_original("Quarterly dividend")
    h.files[evidence["path"]].write_text("TAMPERED",encoding="utf-8")
    with pytest.raises(ValueError,match="PHYSICAL_BYTES_CHANGED"):h.bind()


def test_parent_event_fingerprint_catalogue_cannot_be_substituted(h):
    h.add_original("Quarterly dividend")
    h.bundle["parent_entitlement_event_fingerprints"]=["0"*64]
    with pytest.raises(ValueError,match="PARENT_TYPED_CATALOGUE_CHANGED"):h.bind()


@pytest.mark.parametrize("capture,bound",[("2022-12-05T17:32:39Z","2022-12-05T17:32:39Z"),
    ("2022-12-02T17:32:39Z","2022-12-03T00:00:00Z")])
def test_archived_issuer_availability_uses_later_conservative_bound(h,capture,bound):
    h.payload_update(archive_capture_utc=capture,archive_original_issuer_url=h.payload["source_url"],
                     availability_bound=dict(available_at=bound))
    assert pd.Timestamp(h.bind()["events"]["entitlement_events"][0].available_at)==pd.Timestamp(bound)


def test_archive_capture_cannot_claim_earlier_publication_bound(h):
    h.payload_update(archive_capture_utc="2022-12-05T17:32:39Z",archive_original_issuer_url=h.payload["source_url"])
    with pytest.raises(ValueError):h.bind()


@pytest.mark.parametrize("changes",[dict(archive_capture_utc="2026-01-01T00:00:00Z"),
    dict(archive_original_issuer_url="https://other.example/FAKE_document")])
def test_archive_capture_rejects_future_or_wrong_original_document(h,changes):
    h.payload_update(archive_capture_utc="2022-12-05T17:32:39Z",archive_original_issuer_url=h.payload["source_url"],
                     availability_bound=dict(available_at="2022-12-05T17:32:39Z"))
    h.payload_update(**changes)
    with pytest.raises(ValueError):h.bind()


def test_direct_issuer_ex_preserved_after_same_canonical_rule_check(h):
    h.payload_update(ex_directly_declared=True,source_declared_ex_date="2023-01-19")
    proof=h.bind()["receipt"]["proofs"][0]
    assert proof["source_ex_directly_declared"] is True
    assert proof["source_declared_ex_date"]=="2023-01-19"
    assert proof["ex_status"]=="RESEARCH_NORMAL_SMALL_CASH_DERIVED_FROM_RECORD_AND_FROZEN_CALENDAR"


@pytest.mark.parametrize("direct",["2023-01-20",None])
def test_direct_issuer_ex_conflict_is_not_silently_derived_away(h,direct):
    h.payload_update(ex_directly_declared=True,source_declared_ex_date=direct)
    with pytest.raises(ValueError):h.bind()


def test_direct_ex_flag_cannot_be_string(h):
    h.payload_update(ex_directly_declared="True",source_declared_ex_date="2023-01-19")
    with pytest.raises(ValueError,match="DECLARATION_FLAG_INVALID"):h.bind()


def enable_historical_ex_opt_in(h):
    vendor = dict(ticker="AAA", effective_date="2023-01-19",
        reason="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY",
        source_reference="D:/FAKE_ONLY/original_catalogue.json", source_fingerprint="a"*64)
    h.vendor = vendor
    h.original["unsupported_events"] = (vendor, h.raw_flag)
    h.entry["original_unsupported_keys"] = [vendor]
    h.audit["source_events"] = [vendor]
    h.audit_update()
    facts = dict(clock_role="POST_VERIFIED_ACCOUNTING_ONLY", available_at=None,
        ticker="AAA", security_id=h.entry["identity_binding"]["security_id"],
        security_type="COMMON_STOCK", listing_identity="NYSE:AAA", identity_unique=True,
        issuer_jurisdiction="CA", listed_exchange_jurisdiction="US",
        exchange_rule_applicability="NYSE_LISTED_RAW_USD_COMMON_SHARE",
        exchange_listing_source_reference="https://issuer.example/FAKE_nyse_common",
        exchange_listing_source_fingerprint="f"*64, issuer_source_fingerprint="f"*64,
        identity_source_fingerprint="f"*64, currency="USD", amount_unit=cash.USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=cash.RAW_OLD_SHARE_COORDINATE, ordinary_cash_confirmed=True,
        noncash_flags_absent=True, special_or_due_bill_indicator=False, late_notice_indicator=False,
        record_date=h.payload["record_date"], pay_date=h.payload["pay_date"],
        publication_calendar_date=h.payload["publication_date"],
        pay_date_status="SOURCE_FIXED_ANNOUNCED_SCHEDULE", cash_per_raw_share=2.,
        issuer_history_ex_dates=[],
        ex_date_provenance_role="DERIVED_NYSE_NORMAL_EX_FROM_RECORD_DATE_MATCHED_EXACT_FROZEN_EVENT",
        exact_frozen_event_key=vendor, frozen_event_key_sha256=cash._hash(vendor),
        frozen_event_exact_row_count=1, frozen_catalogue_source_fingerprint="c"*64,
        prior_raw_close=dict(ticker="AAA", security_id=h.entry["identity_binding"]["security_id"],
            raw_close=100., trade_date="2023-01-18", price_coordinate="RAW_CLOSE",
            quantity_coordinate=cash.RAW_OLD_SHARE_COORDINATE, source_fingerprint="d"*64))
    h.bundle["historical_calendar_binding"] = dict(status="SOURCE_BOUND_LEGAL_SESSION_CALENDAR",
        session_dates_sha256=cash._hash([str(d.date()) for d in h.dates]),
        source_reference="D:/FAKE_ONLY/calendar.json", source_fingerprint="e"*64)
    h.bundle["historical_rule_sources"] = {"TPLUS2": dict(effective_from="2017-09-05",
        effective_until_exclusive="2024-05-28", kind="FINRA_17_19_NORMAL_SMALL_CASH",
        source_reference="D:/FAKE_ONLY/rule.pdf", source_fingerprint="b"*64)}
    h.payload_update(source_scope="FROZEN_PRE2026_NYSE_COMMON_USD", historical_ex_adjudication_input=facts)
    return facts


def test_historical_ex_scope_reuses_canonical_owner_without_changing_quantity_or_clock(h):
    facts = enable_historical_ex_opt_in(h)
    before = copy.deepcopy(h.original)
    result = h.bind()
    proof = result["receipt"]["proofs"][0]["historical_ex_adjudication"]
    assert proof["status"] == "ADJUDICATED_RESEARCH_EX_DATE"
    assert proof["available_at"] is None and not proof["production_qualified"]
    assert "vendor_named_ex_date" not in facts
    event = result["events"]["entitlement_events"][0]
    assert event.cash_per_old_share == 2. and event.pay_date == "2023-02-01"
    assert result["receipt"]["proofs"][0]["research_cash_not_before_date"] == "2023-02-02"
    assert result["receipt"]["removed_keys"] == 1 and h.original == before


@pytest.mark.parametrize("change", ["amount", "event_date", "price", "wrong_venue", "clock", "rule", "duplicate"])
def test_historical_adjudication_cannot_detach_from_actual_event_endpoint_or_identity(h, change):
    facts = enable_historical_ex_opt_in(h)
    if change == "amount": facts["cash_per_raw_share"] = 1.
    elif change == "event_date": facts["exact_frozen_event_key"] = dict(facts["exact_frozen_event_key"], effective_date="2023-01-18")
    elif change == "price": facts["prior_raw_close"]["raw_close"] = 200.
    elif change == "wrong_venue": facts["listing_identity"] = "TSX:AAA"
    elif change == "clock": facts["available_at"] = "2022-12-03T00:00:00Z"
    elif change == "rule": h.bundle["historical_rule_sources"]["TPLUS2"]["kind"] = "UNKNOWN"
    else: facts["frozen_event_exact_row_count"] = 2
    h.payload_update(historical_ex_adjudication_input=facts)
    with pytest.raises(ValueError, match="CA_HISTORICAL"):
        h.bind()


# Explicit new descendant parent-cash source corroboration; pure synthetics.
from types import FunctionType
from scripts.research.a2.evaluation.reused_policy_pair import ordinary_cash_lifecycle
@pytest.fixture
def parent_cash_h(tmp_path,monkeypatch):
 v=Harness(tmp_path,monkeypatch)
 sid=v.entry['identity_binding']['security_id']
 old=ca.SourceBackedEntitlementEvent('FAKE_PARENT','CASH_DIVIDEND',sid,'AAA','2023-01-19','2023-01-20','2023-02-01','2022-12-02T00:00:00Z',2.,'USD',ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,'TIER1_ISSUER_REGULATOR_EXCHANGE','https://issuer.example/original','c'*64)
 v.original['entitlement_events']=(old,);v.original['entitlement_security_tickers']={sid:'AAA'}
 evidence=v.write(dict(title='Original source fact metadata'))
 norm=v.write(dict(original_source_projection=evidence))
 v.original['entitlement_source_binding']['manifest']['proofs']=[dict(event_fingerprint=old.event_fingerprint,projection=norm)]
 v.bundle['parent_entitlement_event_fingerprints']=[old.event_fingerprint]
 v.bundle['existing_cash_classification']=mod.classify_existing_cash(v.original)
 assert v.bundle['existing_cash_classification'][0]['status']=='LEGACY_NOT_RECLASSIFIED'
 v.entry.update(existing_parent_cash_event=dict(event_id=old.event_id,event_fingerprint=old.event_fingerprint),source_verified_ordinary_parent_cash=True)
 v.owner.apply_entitlement_lifecycle=ca.apply_entitlement_lifecycle;v.owner.SourceBackedEntitlementEvent=ca.SourceBackedEntitlementEvent;v.owner.SourceBackedTerminalEvent=ca.SourceBackedTerminalEvent
 return v

def test_one_original_event_preserved_exact_new_source_clock_explicit(parent_cash_h):
 before=copy.deepcopy(parent_cash_h.original);old=parent_cash_h.original['entitlement_events'][0];r=parent_cash_h.bind()
 assert parent_cash_h.original==before and len(r['events']['entitlement_events'])==1 and asdict(r['events']['entitlement_events'][0])==asdict(old)
 assert r['events']['entitlement_events'][0].event_fingerprint==old.event_fingerprint
 assert r['receipt']['added_events']==0 and r['receipt']['corroborated_parent_cash_events']==1 and r['receipt']['removed_keys']==1
 assert r['events']['unsupported_events']==(parent_cash_h.raw_flag,)
 assert r['ordinary_cash_event_fingerprints']==frozenset((old.event_fingerprint,))
 proof=r['receipt']['proofs'][0];assert proof['original_available_at']=='2022-12-02T00:00:00Z' and proof['new_source_publication_bound']!='2022-12-02T00:00:00Z'
 appended=r['events']['entitlement_source_binding']['manifest']['parent_ordinary_cash_corroborations'][0]
 assert appended['new_source_account_identity_not_old_account_equivalence'] is True and appended['original_classification']==parent_cash_h.bundle['existing_cash_classification'][0]

def test_ordinary_clock_uses_same_owner_helper_not_new_payment_engine(parent_cash_h):
 old=parent_cash_h.original['entitlement_events'][0];r=parent_cash_h.bind()
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 fn,receipt=ordinary_cash_lifecycle(parent_cash_h.owner,r['events'],r['ordinary_cash_event_fingerprints'],clone=clone)
 assert ca._entitlement_pay_date(old)=='2023-02-01' and fn.__globals__['_entitlement_pay_date'](old)=='2023-02-02'
 assert receipt['events'][0]['issuer_pay_date']=='2023-02-01' and receipt['events'][0]['research_cash_not_before_date']=='2023-02-02'
 assert ca._entitlement_pay_date(old)=='2023-02-01'

@pytest.mark.parametrize('field,value',[('event_id','OTHER'),('event_fingerprint','0'*64)])
def test_parent_ref_requires_exact_id_and_typed_hash(parent_cash_h,field,value):
 parent_cash_h.entry['existing_parent_cash_event'][field]=value
 with pytest.raises(ValueError):parent_cash_h.bind()

def test_parent_ordinary_class_permission_must_be_explicit(parent_cash_h):
 del parent_cash_h.entry['source_verified_ordinary_parent_cash']
 with pytest.raises(ValueError,match='EXACT_ORIGINAL_CASH_EVENT_REF'):parent_cash_h.bind()

@pytest.mark.parametrize('field,value',[('old_security_id','OTHER_SID'),('ticker','BBB'),('ex_date','2023-01-18'),('record_date','2023-01-21'),('pay_date','2023-02-02'),('cash_per_old_share',1.),('currency','EUR'),('amount_unit','PER_INDEX_UNIT'),('quantity_coordinate','INDEX_UNITS'),('action_type','LIQUIDATING_DIVIDEND'),('source_type','UNKNOWN'),('source_fingerprint','BAD'),('available_at','2023-01-19T20:00:00Z')])
def test_all_parent_security_terms_and_authority_still_required(parent_cash_h,field,value):
 old=parent_cash_h.original['entitlement_events'][0];corrupt=copy.copy(old);object.__setattr__(corrupt,field,value)
 parent_cash_h.original['entitlement_events']=(corrupt,);parent_cash_h.entry['existing_parent_cash_event']['event_fingerprint']=corrupt.event_fingerprint;parent_cash_h.bundle['parent_entitlement_event_fingerprints']=[corrupt.event_fingerprint]
 with pytest.raises(ValueError):parent_cash_h.bind()

def test_double_corroboration_cannot_double_remove_or_reclassify(parent_cash_h):
 parent_cash_h.bundle['events'].append(copy.deepcopy(parent_cash_h.entry))
 with pytest.raises(ValueError):parent_cash_h.bind()

def test_unmarked_duplicate_cash_still_rejected(parent_cash_h):
 del parent_cash_h.entry['existing_parent_cash_event'];del parent_cash_h.entry['source_verified_ordinary_parent_cash']
 with pytest.raises(ValueError,match='DUPLICATE_OR_PARALLEL_CASH_EVENT'):parent_cash_h.bind()

@pytest.mark.parametrize('field,value',[('share_event',True),('manual_wolf',True),('factor_a',0.)])
def test_original_parallel_share_and_manual_gate_remains(parent_cash_h,field,value):
 parent_cash_h.audit['audit_rows'][0][field]=value;parent_cash_h.audit_update()
 with pytest.raises(ValueError,match='PARALLEL_SHARE_OR_NONCASH'):parent_cash_h.bind()

def test_exact_original_full_key_and_audit_required(parent_cash_h):
 parent_cash_h.entry['original_unsupported_keys']=[dict(parent_cash_h.vendor,missing_source_binding=True)]
 with pytest.raises(ValueError,match='EXACT_UNIQUE_ORIGINAL_TRANSFORM_KEY'):parent_cash_h.bind()

def test_false_ordinary_flag_cannot_corroborate(parent_cash_h):
 parent_cash_h.payload_update(ordinary_cash_dividend=False)
 with pytest.raises(ValueError):parent_cash_h.bind()

def test_parent_original_projection_bytes_cannot_be_ignored(parent_cash_h):
 p=parent_cash_h.original['entitlement_source_binding']['manifest']['proofs'][0]['projection'];parent_cash_h.files[p['path']].write_bytes(b'CHANGED')
 with pytest.raises(ValueError,match='PHYSICAL_BYTES_CHANGED'):parent_cash_h.bind()


# Exact physical custody transport of nested immutable post-verified source refs.
@pytest.fixture
def nested_custody_h(h):
 facts=enable_historical_ex_opt_in(h)
 old=h.write(dict(fake_original_producer_bytes='immutable original v1'))
 custody=h.write(dict(fake_original_producer_bytes='immutable original v1'))
 predecessor=h.write(dict(schema=mod.SCHEMA,source_refs=[old]))
 h.files[old['path']].write_text('different current producer bytes',encoding='utf-8')
 payload=dict(schema='B_FROZEN_HISTORY_POST_VERIFIED_CASH_SOURCE_PROJECTION_V1',clock_role='POST_VERIFIED_ACCOUNTING_ONLY',historical_available_at=None,original_record_year_conflict_preserved=True,strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False,source_projection=facts,source_scope='FROZEN_PRE2026_NYSE_COMMON_USD',identity_binding=copy.deepcopy(h.entry['identity_binding']),prior_raw_close=copy.deepcopy(h.endpoint),exact_original_unsupported_keys=copy.deepcopy(h.entry['original_unsupported_keys']),source_refs=[old],original_pre_ex_announcement=dict(publication_date=h.payload['publication_date'],literal_pay_date=h.payload['pay_date'],literal_record_date='2022-01-20'),later_issuer_history=dict(archive_capture_utc='2023-03-01T12:00:00Z',source_url='https://issuer.example/original_history',record_date='2023-01-20',record_fact_role='LATE_ISSUER_HISTORY_CORROBORATED_HISTORICAL_RECORD_FACT; NOT_PRE_EX_SOURCE_AVAILABILITY',exact_row=dict(cells=['12/01/2022','01/19/2023','01/20/2023','02/01/2023','$2','Regular Cash'])))
 h.entry['fact_ref']=h.write(payload)
 h.bundle.update(post_verified_cash_scope=copy.deepcopy(mod.POST_VERIFIED_SCOPE),predecessor_source_contract_ref=predecessor,inherited_producer_physical_custody_transport=[dict(original_ref=old,custody_ref=custody,original_bytes_unchanged=True,old_ref_not_relabelled_as_current_producer=True,original_ref_present_in_predecessor_source_refs=True)])
 h.bundle['source_refs'].append(custody)
 h.custody_old,h.custody_ref,h.custody_payload,h.custody_predecessor=old,custody,payload,predecessor
 return h

def bind_nested_custody(h):
 bundle_ref=h.write(h.bundle)
 return mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=bundle_ref)

def test_nested_custody_exact_original_literal_preserved_runtime_binder(nested_custody_h):
 h=nested_custody_h;before=copy.deepcopy(h.custody_payload);result=bind_nested_custody(h)
 event=result['events']['entitlement_events'][0]
 assert isinstance(event,ca.ResearchReconstructedCashEvent) and event.available_at is None
 assert result['receipt']['removed_keys']==1 and event.cash_per_old_share==2.
 assert h.custody_payload==before and h.custody_payload['source_refs']==[h.custody_old]
 assert h.files[h.custody_old['path']].read_text()=='different current producer bytes'
 assert result['receipt']['proofs'][0]['historical_availability_qualified'] is False

@pytest.mark.parametrize('mutation',['same_sha','custody_not_new_pin','old_not_predecessor','duplicate','false_bytes','false_role','false_membership','original_still_current','partial_ref','custody_bytes','predecessor_bytes','undeclared_nested','duplicate_predecessor','duplicate_current'])
def test_nested_custody_preserves_all_original_physical_and_subject_gates(nested_custody_h,mutation):
 h=nested_custody_h;tx=h.bundle['inherited_producer_physical_custody_transport'][0]
 if mutation=='same_sha':tx['custody_ref']=dict(tx['custody_ref'],sha256='0'*64)
 elif mutation=='custody_not_new_pin':h.bundle['source_refs'].remove(h.custody_ref)
 elif mutation=='old_not_predecessor':h.bundle['predecessor_source_contract_ref']=h.write(dict(source_refs=[]))
 elif mutation=='duplicate':h.bundle['inherited_producer_physical_custody_transport'].append(copy.deepcopy(tx))
 elif mutation=='false_bytes':tx['original_bytes_unchanged']=False
 elif mutation=='false_role':tx['old_ref_not_relabelled_as_current_producer']=False
 elif mutation=='false_membership':tx['original_ref_present_in_predecessor_source_refs']=False
 elif mutation=='original_still_current':h.bundle['source_refs'].append(h.custody_old)
 elif mutation=='partial_ref':tx['original_ref']=dict(tx['original_ref'],bytes=7)
 elif mutation=='custody_bytes':h.files[h.custody_ref['path']].write_text('corrupt custody')
 elif mutation=='predecessor_bytes':h.files[h.custody_predecessor['path']].write_text('corrupt predecessor')
 elif mutation=='duplicate_predecessor':h.bundle['predecessor_source_contract_ref']=h.write(dict(source_refs=[h.custody_old,h.custody_old]))
 elif mutation=='duplicate_current':h.bundle['source_refs'].append(h.custody_ref)
 else:
  extra=h.write(dict(source='separate immutable source'))
  h.files[extra['path']].write_text('corrupt undeclared nested source')
  h.custody_payload['source_refs'].append(extra);h.entry['fact_ref']=h.write(h.custody_payload)
 with pytest.raises(ValueError):bind_nested_custody(h)

def test_nested_custody_transport_requires_current_physical_bundle_ref(nested_custody_h):
 h=nested_custody_h
 with pytest.raises(ValueError,match='PINNED_CUSTODY_PREDECESSOR'):h.bind()
 bad_ref=h.write(dict(h.bundle,source_version_id='different frozen bundle'))
 with pytest.raises(ValueError,match='PINNED_CUSTODY_PREDECESSOR'):
  mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=bad_ref)

def test_nested_custody_undeclared_transport_retains_old_physical_rejection(nested_custody_h):
 h=nested_custody_h;del h.bundle['inherited_producer_physical_custody_transport']
 with pytest.raises(ValueError,match='PHYSICAL_BYTES_CHANGED'):bind_nested_custody(h)


# Explicit historical ADS admission uses the real adapter/terms/lifecycle.
# All files and units are synthetic; no historical account is loaded.
def _source_declared_ads_case(h, *, enable=True):
    source_url="https://issuer.example/FAKE_direct_ads_notice"
    h.payload=dict(event_key="FAKE_ADS_AAA_2023Q1",ticker="AAA",issuer="FAKE Issuer",
        listed_exchange="NYSE",security_type="AMERICAN_DEPOSITARY_SHARE",
        currency="USD",currency_confidence="EXPLICIT_USD",
        amount_unit=ca.USD_PER_RAW_OLD_SHARE,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        cash_per_raw_ex_pretrade_common_share=None,cash_per_raw_ex_pretrade_ads=1.2,
        record_date="2023-01-20",scheduled_pay_date="2023-02-01",
        publication_date="2022-12-01",available_at_upper_bound="2022-12-03T00:00:00Z",
        ex_date_binding=dict(value="2023-01-19"),ordinary_cash_dividend=True,source_url=source_url,
        ads_unit_evidence=dict(unit_status="SOURCE_DECLARED_PER_ADS",
            source_unit="USD_PER_ADS_GROSS_BEFORE_APPLICABLE_FEES",cash_per_raw_ads=1.2,
            source_reference=source_url,ordinary_shares_per_ads=6,cash_per_raw_ordinary_share_usd=.2),
        cash_deductions=dict(depositary_fees="SOURCE_SAYS_LESS_APPLICABLE_FEES_AMOUNT_UNKNOWN",
            withholding="UNKNOWN",actual_broker_cash="NOT_OBSERVED"))
    body=dict(security_id=cash.source_derived_security_id("FAKE Issuer","AAA","NYSE:AAA",
            "AMERICAN_DEPOSITARY_SHARE"),identity_kind="SOURCE_DERIVED_ISSUER_COMMON_CLASS",
        issuer="FAKE Issuer",ticker="AAA",listing_identity="NYSE:AAA",
        security_type="AMERICAN_DEPOSITARY_SHARE")
    h.entry["identity_binding"]=dict(body,identity_payload_sha256=mod._hash(body),
        source_reference="https://issuer.example/FAKE_ADS_identity",
        source_fingerprint="f"*64,available_at="2022-12-03T00:00:00Z")
    h.entry["fact_ref"]=h.write(h.payload)
    if enable:
        h.bundle["source_declared_ads_cash_scope"]=copy.deepcopy(mod.SOURCE_DECLARED_ADS_CASH_SCOPE)
    return h


def _bind_pinned_source_declared_ads(h, *, bundle_ref=None):
    ref=h.write(h.bundle) if bundle_ref is None else bundle_ref
    return mod.bind_source_account_descendant(h.owner,h.original,h.bundle,
        account_dates=h.dates,bundle_ref=ref)


def test_source_declared_ads_pinned_scope_binds_direct_gross_and_keeps_parent_same_sid(h):
    _source_declared_ads_case(h)
    sid=h.entry["identity_binding"]["security_id"]
    old=ca.SourceBackedEntitlementEvent("FAKE_OLD_ADS","CASH_DIVIDEND",sid,"AAA",
        "2023-02-01","2023-02-02","2023-03-01","2022-12-03T00:00:00Z",.6,"USD",
        ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,
        "TIER1_ISSUER_REGULATOR_EXCHANGE","https://issuer.example/FAKE_old_ads","c"*64)
    original_projection=h.write(dict(title="Quarterly cash dividend"))
    normalized=h.write(dict(original_source_projection=original_projection))
    h.original.update(entitlement_events=(old,),entitlement_security_tickers={sid:"AAA"})
    h.original["entitlement_source_binding"]["manifest"]["proofs"]=[
        dict(event_fingerprint=old.event_fingerprint,projection=normalized)]
    h.bundle["parent_entitlement_event_fingerprints"]=[old.event_fingerprint]
    h.bundle["existing_cash_classification"]=mod.classify_existing_cash(h.original)
    before=copy.deepcopy(h.original)
    result=_bind_pinned_source_declared_ads(h)
    event=next(e for e in result["events"]["entitlement_events"] if e.ex_date=="2023-01-19")
    assert sid.startswith("SOURCE_ISSUER_ADS_CLASS:") and event.old_security_id==sid
    assert event.cash_per_old_share==1.2 and event.quantity_coordinate==ca.RAW_OLD_SHARE_COORDINATE
    assert asdict(next(e for e in result["events"]["entitlement_events"] if e.event_id==old.event_id))==asdict(old)
    assert h.original==before and result["receipt"]["old_event_bytes_unchanged"] is True
    proof=result["receipt"]["proofs"][0]
    assert proof["ads_unit_evidence"]==h.payload["ads_unit_evidence"]
    assert proof["cash_deductions"]==h.payload["cash_deductions"]
    assert proof["broker_payment"]=="NOT_OBSERVED"
    assert "NO_FEE_OR_WITHHOLDING_ESTIMATE" in proof["gross_cash_basis"]
    assert result["receipt"]["source_declared_ads_cash_scope"]==mod.SOURCE_DECLARED_ADS_CASH_SCOPE
    assert result["events"]["entitlement_source_binding"]["manifest"]["source_declared_ads_cash_scope"]==mod.SOURCE_DECLARED_ADS_CASH_SCOPE
    assert result["events"]["corporate_actions"]==h.original["corporate_actions"]
    assert event.event_fingerprint in result["ordinary_cash_event_fingerprints"]


def test_source_declared_ads_quantity_cash_and_existing_clock_never_multiply_by_ratio(h):
    _source_declared_ads_case(h)
    result=_bind_pinned_source_declared_ads(h)
    event=result["events"]["entitlement_events"][0]
    positions={event.old_security_id:3.}
    ex=ca.apply_entitlement_lifecycle((event,),positions,0.,execution_date=event.ex_date,
        session_open_at=cash._clock(pd.Timestamp(event.ex_date),9,30),
        security_tickers=result["events"]["entitlement_security_tickers"],
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,enabled=True)
    assert ex.positions==positions
    assert ex.cash==0. and ex.receivable_value_usd==pytest.approx(3.*1.2)
    assert ex.receivable_value_usd!=pytest.approx(3.*1.2*6)
    assert result["receipt"]["proofs"][0]["research_cash_not_before_date"]=="2023-02-02"
    assert event.pay_date=="2023-02-01" and result["receipt"]["decision_quality_modified"] is False
    assert result["receipt"]["broker_payment_proven"] is False


def test_source_declared_ads_missing_scope_keeps_default_rejection(h):
    _source_declared_ads_case(h,enable=False)
    with pytest.raises(ValueError,match="ADS_EXPLICIT_OPT_IN_REQUIRED"):
        h.bind()


@pytest.mark.parametrize("field,value",[
    ("task_id","OTHER_TASK"),("scientific_identity","PRODUCTION"),
    ("clock_role","POST_VERIFIED_ACCOUNTING_ONLY"),("accounting_clock_convention","PAY_PRE_OPEN"),
    ("scope_start","2022-01-01"),("scope_end_exclusive","2027-01-01"),
    ("security_type","COMMON_STOCK"),("amount_basis","ORDINARY_SHARE_AMOUNT_TIMES_RATIO"),
    ("ordinary_share_ratio_role","POSITION_MULTIPLIER"),
    ("net_cash_and_depositary_fee_authority","NET_FEE_ESTIMATED"),
    ("strict_PIT",True),("production_qualified",True),("quote_qualified",True),("certified_NAV",True),
    ("strict_PIT",0),("additional_authority",False)])
def test_source_declared_ads_scope_mutation_rejected_before_term_admission(h,field,value):
    _source_declared_ads_case(h)
    h.bundle["source_declared_ads_cash_scope"][field]=value
    with pytest.raises(ValueError,match="EXACT_SOURCE_DECLARED_ADS_CASH_SCOPE"):
        _bind_pinned_source_declared_ads(h)


def test_source_declared_ads_scope_requires_physical_exact_bundle_ref(h):
    _source_declared_ads_case(h)
    with pytest.raises(ValueError,match="PINNED_SOURCE_DECLARED_ADS_CASH_SCOPE"):
        h.bind()
    previous=h.write(h.bundle)
    h.bundle["source_version_id"]="MUTATED_AFTER_PIN"
    with pytest.raises(ValueError,match="PINNED_SOURCE_DECLARED_ADS_CASH_SCOPE"):
        _bind_pinned_source_declared_ads(h,bundle_ref=previous)


def test_source_declared_ads_scope_rechecks_physical_bundle_bytes(h):
    _source_declared_ads_case(h)
    ref=h.write(h.bundle)
    h.files[ref["path"]].write_text("CHANGED",encoding="utf-8")
    with pytest.raises(ValueError,match="PHYSICAL_BYTES_CHANGED"):
        _bind_pinned_source_declared_ads(h,bundle_ref=ref)


@pytest.mark.parametrize("mutation",[
    "common_schema_pretends_ads","common_identity_pretends_ads","common_field_present",
    "ordinary_amount_as_ads","ratio_mismatch","ratio_bool","different_unit_source",
    "missing_direct_unit","quantity_coordinate","amount_unit"])
def test_source_declared_ads_existing_unit_source_ratio_and_class_gates_unchanged(h,mutation):
    _source_declared_ads_case(h)
    if mutation=="common_schema_pretends_ads":
        h.payload["id"]="FAKE_COMMON_SHORT_SCHEMA"
    elif mutation=="common_identity_pretends_ads":
        h.entry["identity_binding"]=h.identity("AAA")
    elif mutation=="common_field_present":
        h.payload["cash_per_raw_ex_pretrade_common_share"]=.2
    elif mutation=="ordinary_amount_as_ads":
        h.payload["cash_per_raw_ex_pretrade_ads"]=.2
        h.payload["ads_unit_evidence"]["cash_per_raw_ads"]=.2
    elif mutation=="ratio_mismatch":
        h.payload["ads_unit_evidence"]["ordinary_shares_per_ads"]=5
    elif mutation=="ratio_bool":
        h.payload["ads_unit_evidence"]["ordinary_shares_per_ads"]=True
    elif mutation=="different_unit_source":
        h.payload["ads_unit_evidence"]["source_reference"]="https://issuer.example/DIFFERENT"
    elif mutation=="missing_direct_unit":
        h.payload["ads_unit_evidence"]["unit_status"]="ORDINARY_SHARE_DERIVED"
    elif mutation=="quantity_coordinate":
        h.payload["quantity_coordinate"]="RAW_ORDINARY_SHARES"
    else:
        h.payload["amount_unit"]="USD_PER_ORDINARY_SHARE"
    h.entry["fact_ref"]=h.write(h.payload)
    with pytest.raises(ValueError):
        _bind_pinned_source_declared_ads(h)


@pytest.mark.parametrize("mutation",["net_amount","invalid_amount","pub_early","ordinary_false","late_notice"])
def test_source_declared_ads_ordinary_positive_amount_and_publication_gates_unchanged(h,mutation):
    _source_declared_ads_case(h)
    if mutation=="net_amount":
        h.payload["cash_per_raw_ex_pretrade_ads"]=1.1
    elif mutation=="invalid_amount":
        h.payload["cash_per_raw_ex_pretrade_ads"]=-1.2
        h.payload["ads_unit_evidence"]["cash_per_raw_ads"]=-1.2
        h.payload["ads_unit_evidence"]["cash_per_raw_ordinary_share_usd"]=-.2
    elif mutation=="pub_early":
        h.payload["available_at_upper_bound"]="2022-12-02T00:00:00Z"
    elif mutation=="ordinary_false":
        h.payload["ordinary_cash_dividend"]=False
    else:
        h.payload["publication_date"]="2023-01-11"
        h.payload["available_at_upper_bound"]="2023-01-13T00:00:00Z"
    h.entry["fact_ref"]=h.write(h.payload)
    with pytest.raises(ValueError):
        _bind_pinned_source_declared_ads(h)


def test_source_declared_ads_scope_preserves_real_post_verified_common_transformation(nested_custody_h):
    h=nested_custody_h
    baseline=bind_nested_custody(h)
    h.bundle["source_declared_ads_cash_scope"]=copy.deepcopy(mod.SOURCE_DECLARED_ADS_CASH_SCOPE)
    scoped=bind_nested_custody(h)
    assert [asdict(e) for e in scoped["events"]["entitlement_events"]]==[asdict(e) for e in baseline["events"]["entitlement_events"]]
    assert scoped["receipt"]["proofs"]==baseline["receipt"]["proofs"]
    assert scoped["ordinary_cash_event_fingerprints"]==baseline["ordinary_cash_event_fingerprints"]
    assert scoped["events"]["entitlement_events"][0].available_at is None
    assert "ads_unit_evidence" not in scoped["receipt"]["proofs"][0]


def test_source_declared_ads_scope_cannot_widen_real_post_verified_subject(nested_custody_h):
    h=nested_custody_h
    h.bundle["source_declared_ads_cash_scope"]=copy.deepcopy(mod.SOURCE_DECLARED_ADS_CASH_SCOPE)
    h.custody_payload["source_projection"]["security_type"]="AMERICAN_DEPOSITARY_SHARE"
    h.entry["fact_ref"]=h.write(h.custody_payload)
    with pytest.raises(ValueError,match="POST_VERIFIED_EXACT_SUBJECT"):
        bind_nested_custody(h)


def test_source_declared_ads_absent_default_common_and_scope_enabled_common_have_same_terms(h):
    baseline=h.bind()
    assert "source_declared_ads_cash_scope" not in baseline["receipt"]
    assert "source_declared_ads_cash_scope" not in baseline["events"]["entitlement_source_binding"]["manifest"]
    assert "ads_unit_evidence" not in baseline["receipt"]["proofs"][0]
    h.bundle["source_declared_ads_cash_scope"]=copy.deepcopy(mod.SOURCE_DECLARED_ADS_CASH_SCOPE)
    scoped=_bind_pinned_source_declared_ads(h)
    assert [asdict(e) for e in scoped["events"]["entitlement_events"]]==[asdict(e) for e in baseline["events"]["entitlement_events"]]
    assert scoped["receipt"]["proofs"]==baseline["receipt"]["proofs"]
    assert scoped["ordinary_cash_event_fingerprints"]==baseline["ordinary_cash_event_fingerprints"]
    assert scoped["events"]["unsupported_events"]==baseline["events"]["unsupported_events"]
    assert scoped["events"]["corporate_actions"]==baseline["events"]["corporate_actions"]



def _source_declared_nontrading_record_case(h):
    h.payload_update(record_date="2023-01-21", ex_directly_declared=True,
        source_declared_ex_date="2023-01-19")
    h.bundle["source_declared_cash_ex_scope"] = copy.deepcopy(mod.SOURCE_DECLARED_CASH_EX_SCOPE)


def _bind_pinned_source_declared_ex(h):
    ref = h.write(h.bundle)
    return mod.bind_source_account_descendant(h.owner, h.original, h.bundle,
        account_dates=h.dates, bundle_ref=ref)


def test_source_declared_ex_real_adapter_keeps_record_literal_and_cash_clock(h):
    _source_declared_nontrading_record_case(h)
    result = _bind_pinned_source_declared_ex(h)
    event = result["events"]["entitlement_events"][0]
    assert event.ex_date == "2023-01-19" and event.record_date == "2023-01-21"
    assert event.cash_per_old_share == 2. and event.pay_date == "2023-02-01"
    assert event.available_at == "2022-12-03 00:00:00+00:00"
    assert result["ordinary_cash_event_fingerprints"] == {event.event_fingerprint}
    assert result["events"]["unsupported_events"] == (h.raw_flag,)
    proof = result["receipt"]["proofs"][0]
    assert proof["ex_rule"] == "SOURCE_DECLARED_EX_RESEARCH"
    assert proof["ex_status"] == "RESEARCH_SOURCE_DECLARED_EX_WITH_LITERAL_RECORD_AND_UNCHANGED_FROZEN_CALENDAR"
    assert proof["source_declared_ex_date"] == "2023-01-19"
    assert result["receipt"]["source_declared_cash_ex_scope"] == mod.SOURCE_DECLARED_CASH_EX_SCOPE
    assert "2023-01-21" not in result["events"]["entitlement_source_binding"]["manifest"].get("calendar", ())


@pytest.mark.parametrize("mutation", ["scope_absent", "scope_false_flag", "scope_integer_flag", "missing_pin", "changed_bundle_pin", "missing_direct_date", "direct_false", "direct_integer", "bad_date", "late_notice"])
def test_source_declared_ex_real_adapter_rejects_missing_pin_declaration_or_prior_guards(h, mutation):
    _source_declared_nontrading_record_case(h)
    if mutation == "scope_absent": del h.bundle["source_declared_cash_ex_scope"]
    elif mutation == "scope_false_flag": h.bundle["source_declared_cash_ex_scope"]["strict_PIT"] = True
    elif mutation == "scope_integer_flag": h.bundle["source_declared_cash_ex_scope"]["strict_PIT"] = 0
    elif mutation == "missing_pin":
        with pytest.raises(ValueError, match="PINNED_SOURCE_DECLARED_CASH_EX_SCOPE"):
            h.bind()
        return
    elif mutation == "changed_bundle_pin":
        ref = h.write(h.bundle); h.bundle["source_version_id"] += "CHANGED"
        with pytest.raises(ValueError, match="PINNED_SOURCE_DECLARED_CASH_EX_SCOPE"):
            mod.bind_source_account_descendant(h.owner, h.original, h.bundle, account_dates=h.dates, bundle_ref=ref)
        return
    elif mutation == "missing_direct_date": h.payload.pop("source_declared_ex_date")
    elif mutation == "direct_false": h.payload["ex_directly_declared"] = False
    elif mutation == "direct_integer": h.payload["ex_directly_declared"] = 1
    elif mutation == "bad_date": h.payload["source_declared_ex_date"] = "2023-01-18"
    else:
        h.payload["publication_date"] = "2023-01-18"
        h.payload["availability_bound"]["available_at"] = "2023-01-20T00:00:00Z"
    h.entry["fact_ref"] = h.write(h.payload)
    with pytest.raises(ValueError): _bind_pinned_source_declared_ex(h)


def test_source_declared_ex_scope_does_not_change_default_common_derivation(h):
    baseline = h.bind()
    h.bundle["source_declared_cash_ex_scope"] = copy.deepcopy(mod.SOURCE_DECLARED_CASH_EX_SCOPE)
    scoped = _bind_pinned_source_declared_ex(h)
    assert [asdict(e) for e in scoped["events"]["entitlement_events"]] == [asdict(e) for e in baseline["events"]["entitlement_events"]]
    assert scoped["receipt"]["proofs"] == baseline["receipt"]["proofs"]
    assert scoped["ordinary_cash_event_fingerprints"] == baseline["ordinary_cash_event_fingerprints"]


def test_source_declared_ex_scope_does_not_widen_post_verified_branch(nested_custody_h):
    h = nested_custody_h
    baseline = bind_nested_custody(h)
    h.bundle["source_declared_cash_ex_scope"] = copy.deepcopy(mod.SOURCE_DECLARED_CASH_EX_SCOPE)
    scoped = bind_nested_custody(h)
    assert [asdict(e) for e in scoped["events"]["entitlement_events"]] == [asdict(e) for e in baseline["events"]["entitlement_events"]]
    assert scoped["receipt"]["proofs"] == baseline["receipt"]["proofs"]
