"""Thin source binding for the fixed-policy full selector account.

No price adjustment, cash reconstruction, forecast reader or account engine.
All historical facts keep their original pins and their publication limitations.
"""
from __future__ import annotations
import copy
from dataclasses import asdict, fields
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
import joblib
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.full_selector_inputs import FullSelectorReader, ID
from scripts.research.a2.data.joint_input_binding import guard_parquet, sha256
from scripts.research.a2.data import reused_pair_ca_sources as source
from scripts.research.a2.evaluation import continuous_research_account as account
from scripts.research.a2.evaluation import frozen_history_research_quote_domain as quote
from scripts.v22 import corporate_action_transition_r1 as ca

REPO = Path(__file__).resolve().parents[4]
A = "D:/us-tech-quant-results/_maintenance/V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1/source_materialization/"
Q = "D:/us-tech-quant-results/_maintenance/V24_SHARED_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_R1/"
DEFAULT_REFS = {
    "raw_prices": {"path":"D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work/full848raw_pre2026.parquet","sha256":"20057f59e6188ac4a2d35923ec8c1689e43380aefbbc87a1a7c78312616693f8"},
    "market_adapter":{"path":"D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work/selector_replay.py","sha256":"b344fa6f10c08249e21ef590820bab8bf1a8ed46dcfa2459312766f34d8ed4bb"},
    "original_cash_kwargs":{"path":"D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/continuation/cash_r4/inputs/cash_replay_kwargs.joblib","sha256":"abf6d1b0e22651fc87141c214971871332af4ba937716bc8d2e7bc5c7a5d5e4c"},
    "ordinary_sources":{"path":"D:/us-tech-quant-results/_maintenance/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/CA_SOURCE_ACCOUNT_CONTRACT_FAST_TRACK_V17.json","sha256":"6df374d10763819eb870b2ba32aa1e3dcb95654333d31b95d30a2b083348a013"},
    "a_catalogue":{"path":A+"RESEARCH_ENTITLEMENT_CATALOGUE.json","sha256":"06e3520c0b281141dde02d1a507d1750f1da3a7aa470eaa91e3a317859cb0f11"},
    "a_mapping":{"path":A+"SECURITY_ACCOUNTING_MAPPING.json","sha256":"256a602264ca2a96b1ca39a2a2a0ed64f8e3f4df79f4ddd4b7233dd1dd15badf"},
    "a_identity":{"path":A+"FROZEN_ACCOUNTING_IDENTITY_PROJECTION.json","sha256":"2d0649015f5d2713114fd818261a0f106b3ebd345501878fd16ab94521c6b861"},
    "dated_identity":{"path":"D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/cache/prediction_feature_panel_pitguarded_r1.parquet","sha256":"dfe110afcdf13c4b0b43f3402cb844fcda02073d6ed8b6d05a278fbec8495427"},
    "a_authority":{"path":A+"RESEARCH_RUN_CONFIG_PROPOSAL.json","sha256":"4c7bf03f4f765bdff212557765f666a444b10689fc3cbbdad286bceb0935c6ab"},
    "quote_binding":{"path":Q+"source_metadata_final/SOURCE_BINDING_A.json","sha256":"50134a75e1b1e4af195277769a63aefaa468427e81790ce220bba5e759d880e4"},
    "quote_classification":{"path":Q+"source_metadata_final/QUOTE_DOMAIN_CLASSIFICATION.json","sha256":"0509ad75a4bc549833b7109e2763addf369994631d9600e782043483dc97ceba"},
    "quote_composer":{"path":"D:/us-tech-quant-cache/V24/V24_SHARED_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_R1/source_audit/run_shared_quote_B_descendant.py","sha256":"ad6d9b90652fff35804c0d18723fed5bff3a8bad64bb05bc8c82e078d942d07c"},
}
OLD_CA = {"path":"D:/us-tech-quant/scripts/v22/corporate_action_transition_r1.py","sha256":"fe3a4ccded25a56adfe8631aadd28606b970c74e3514a71c1ea43d411aa46c08"}
OWNERS = {
    "account":{"path":str(REPO/"scripts/research/a2/evaluation/continuous_research_account.py"),"sha256":"4dd3b001485afab6bff4bb618391814f34063f7e262fb9a51a9864103fef9253"},
    "ca":{"path":str(REPO/"scripts/v22/corporate_action_transition_r1.py"),"sha256":"c12c7f1ac90016a11bcc782fcf97e30f45a3b8458cf4a188e0a589b240d04f61"},
    "cash_adapter":{"path":str(REPO/"scripts/research/a2/data/reused_pair_ca_sources.py"),"sha256":"1775b34066887c59b1da10e83121c6d860575d050edded5f59040a457684ba98"},
    "quote_owner":{"path":str(REPO/"scripts/research/a2/evaluation/frozen_history_research_quote_domain.py"),"sha256":"eda136406c8de2c9053441943e751c6b16d5a56307ae118b904ac8fb773b55f4"},
    "snapshot_owner":{"path":str(REPO/"scripts/research/a2/evaluation/joint_frozen_history_r3.py"),"sha256":"2a687cf5c92b493a183dfbf6f51444a52cab3f58c1f3f462778358002d9fa5f4"},
}
ACCOUNT = dict(base_currency="USD",initial_nav=3000.,initial_cash=3000.,initial_holdings=[],
    fractional_shares=True,integer_share_rounding=False,cash_interest=0,transaction_cost_bps=0,
    financing=False,borrowed_cash=False,long_only=True,max_positions=20,max_weight=.05,
    max_invested=1.,capacity_fraction=None)
FRICTION = dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE",scenario_id=ID+"_10BPS",
    one_way_bps=10,fee_bps=0,benchmark="NEXT_RAW_OPEN",authority="HYPOTHETICAL_RESEARCH_SCENARIO")


def require(ok, code):
    if not ok: raise ValueError(code)


def digest(value):
    return hashlib.sha256(ca.canonical_bytes(value)).hexdigest()


def _same_ref(a,b):
    return (Path(a["path"]) == Path(b["path"]) and a["sha256"] == b["sha256"])


def custody_reader(transports):
    """One declared same-byte legacy CA transport; never a live-source waiver."""
    tx = tuple(transports)
    require(len(tx) == 1 and set(tx[0]) == {"original_ref","custody_ref","original_bytes_unchanged"},
        "EXACT_LEGACY_CA_CUSTODY_TRANSPORT_REQUIRED")
    t = tx[0]
    require(_same_ref(t["original_ref"], OLD_CA) and t["original_bytes_unchanged"] is True
        and set(t["custody_ref"]) == {"path","sha256"}
        and t["custody_ref"]["sha256"] == OLD_CA["sha256"]
        and Path(t["custody_ref"]["path"]).is_relative_to(resolve(REPO).backtest_root),
        "SAME_BYTE_CA_CUSTODY_TRANSPORT_REQUIRED")
    require(sha256(t["custody_ref"]["path"]) == OLD_CA["sha256"],"CA_CUSTODY_BYTES_CHANGED")
    checked = {}
    def pin(ref):
        require(isinstance(ref,dict) and {"path","sha256"}.issubset(ref),
            "PHYSICAL_SOURCE_REFERENCE_REQUIRED")
        r = t["custody_ref"] if _same_ref(ref,OLD_CA) else ref
        key = (r["path"],r["sha256"])
        if key not in checked:
            require(Path(r["path"]).drive.upper() == "D:" and sha256(r["path"]) == r["sha256"],
                "ACCOUNT_SOURCE_CUSTODY_CHANGED:"+r["path"])
            checked[key] = True
        return Path(r["path"])
    def read(ref):
        return json.loads(pin(ref).read_text(encoding="utf-8-sig"))
    return pin, read


def private_source_adapter(pin,read):
    """Keep existing source validators and all helper calls in one private namespace."""
    ns = dict(vars(source))
    for name, value in tuple(ns.items()):
        if isinstance(value,FunctionType) and value.__module__ == source.__name__:
            fn = FunctionType(value.__code__,ns,value.__name__,value.__defaults__,value.__closure__)
            fn.__kwdefaults__ = value.__kwdefaults__
            ns[name] = fn
    ns.update(_pin=pin,_read=read)
    return SimpleNamespace(**ns)


def identity_links(keys,mapping,projection,dated_identity=None):
    """Exact original CUSIP metadata plus dated raw-share mapping; no ticker alias."""
    f = keys[["signal_date","security_uid","ticker","cusip"]].copy()
    f.signal_date = pd.to_datetime(f.signal_date)
    require(not f.duplicated(["signal_date","security_uid"]).any()
        and f.security_uid.eq("CUSIP:"+f.cusip.astype(str).str.strip().str.upper()).all(),
        "FULL_U_UID_METADATA_CHANGED")
    banks = {}
    for row in projection["rows"]:
        require(row["ticker"] not in banks, "DUPLICATE_ORIGINAL_IDENTITY_PROJECTION")
        banks[row["ticker"]] = set(row["observed_decision_security_ids"])
    dated={}
    if dated_identity is not None:
        d=dated_identity[["signal_date","ticker","security_id","moomoo_transport_code"]].copy()
        d.signal_date=pd.to_datetime(d.signal_date)
        require(not d.duplicated(["signal_date","ticker"]).any(),"ORIGINAL_DATED_IDENTITY_KEY_AMBIGUOUS")
        dated={(r.signal_date,r.ticker):(str(r.security_id).strip().upper(),r.moomoo_transport_code)
            for r in d.itertuples()}
    links, gaps = [], []
    for ticker,group in f.groupby("ticker",sort=True):
        records = [r for r in mapping["records"] if r["ticker"] == ticker]
        original = banks.get(ticker,set())
        for row in group.itertuples():
            matches = [r for r in records if pd.Timestamp(r["start"]) <= row.signal_date < pd.Timestamp(r["end"])
                and r["coordinate"] == "RAW_ACTUAL_SHARE"]
            cusip = row.security_uid.removeprefix("CUSIP:")
            dated_exact=dated.get((row.signal_date,ticker))==(cusip,"US."+ticker)
            transport_exact=(matches and matches[0]["sid"]=="FROZEN_RAW_TRANSPORT_CODE:US."+ticker
                and (dated_exact or (dated_identity is None and len(original)==1)))
            basis=mapping.get("basis_by_ticker",{}).get(ticker,{})
            issuer_exact=(matches and dated_exact
                and basis.get("kind")=="EXACT_REUSED_SOURCE_CASH_ISSUER_CLASS"
                and basis.get("source_sid")==matches[0]["sid"]
                and basis.get("not_a_CUSIP_claim") is False
                and isinstance(basis.get("source_ref"),dict)
                and _same_ref(basis["source_ref"],DEFAULT_REFS["original_cash_kwargs"])
                and matches[0]["sid"].startswith(("SOURCE_ISSUER_COMMON_CLASS:","SOURCE_ISSUER_ADS_CLASS:")))
            exact = (len(matches)==1 and cusip in original
                and (matches[0]["sid"] in (cusip,row.security_uid) or transport_exact or issuer_exact)
                and (dated_identity is None or dated_exact))
            if not exact:
                gaps.append(dict(signal_date=str(row.signal_date.date()),security_uid=row.security_uid,
                    ticker=ticker,reason="NO_UNIQUE_DATED_ORIGINAL_CUSIP_RAW_SHARE_LINK"))
            else:
                links.append(dict(signal_date=row.signal_date,security_uid=row.security_uid,
                    ticker=ticker,accounting_sid=matches[0]["sid"]))
    return pd.DataFrame(links),gaps


def _cash_key(event):
    return (event.ticker,event.ex_date)


def _cash_terms(event):
    return (event.old_security_id,event.ticker,event.ex_date,event.record_date,event.pay_date,
        event.cash_per_old_share,event.currency,event.amount_unit,event.quantity_coordinate,event.action_type)


def _typed_a(records):
    result=[]
    for record in records:
        item=dict(record); expected=item.pop("event_fingerprint")
        cls=ca.ResearchReconstructedTerminalEvent if item.get("action_type")=="MERGER_CASH_CONVERSION" else ca.SourceBackedEntitlementEvent
        require(set(item)=={f.name for f in fields(cls)}, "A_EXACT_DECLARED_TYPED_LAYOUT_REQUIRED")
        value=cls(**item)
        require(value.event_fingerprint==expected, "A_ORIGINAL_TYPED_FINGERPRINT_CHANGED")
        result.append(value)
    return tuple(result)


def combine_cash_and_terminal(descendant,a_events,terminal_authority,contract_ref):
    """Keep original A catalogue, exact corroborations and new ordinary source facts once."""
    b=dict(descendant["events"]); b_events=tuple(b["entitlement_events"])
    by_key={_cash_key(e):e for e in b_events}
    require(len(by_key)==len(b_events),"B_DUPLICATE_ECONOMIC_CASH_KEY")
    ordinary=set(descendant["ordinary_cash_event_fingerprints"])
    retained=list(b_events); corroborations=[]
    for event in a_events:
        if isinstance(event,ca.SourceBackedTerminalEvent):
            retained.append(event);continue
        prior=by_key.get(_cash_key(event))
        if prior is None:
            retained.append(event)
        else:
            require(_cash_terms(prior)==_cash_terms(event),"A_B_CASH_FACT_CONFLICT_NO_CHOICE_ALLOWED")
            retained.remove(prior);retained.append(event)
            if prior.event_fingerprint in ordinary:
                ordinary.remove(prior.event_fingerprint);ordinary.add(event.event_fingerprint)
            corroborations.append(dict(original_A_fingerprint=event.event_fingerprint,
                B_source_fingerprint=prior.event_fingerprint,original_A_bytes_preserved=True,cash_counted_once=True))
    retained.sort(key=lambda e:(str(ca._entitlement_effective_day(e)),e.event_id))
    require(len({e.event_id for e in retained})==len(retained),"MERGED_EVENT_ID_CONFLICT")
    admission=copy.deepcopy(b.get("research_account_authority",{}).get("frozen_history_cash_admission"))
    historical={e.event_fingerprint for e in retained if isinstance(e,ca.ResearchReconstructedCashEvent)}
    if admission is not None:
        admission["events"]=[e for e in admission["events"] if e["event_fingerprint"] in historical]
    require(historical or admission is None,"EMPTY_RECONSTRUCTED_CASH_ADMISSION")
    manifest=dict(schema="C_FULL_SELECTOR_FIXED_POLICY_SOURCE_COMPOSITION_V1",
        original_B_source_binding=b["entitlement_source_binding"],A_exact_corroborations=corroborations,
        event_fingerprints=[e.event_fingerprint for e in retained],original_A_bytes_preserved=True)
    tickers=dict(b["entitlement_security_tickers"])
    for e in retained:
        require(e.old_security_id not in tickers or tickers[e.old_security_id]==e.ticker,"CASH_SECURITY_MAPPING_CONFLICT")
        tickers[e.old_security_id]=e.ticker
    authority=dict(schema="C_FULL_SELECTOR_FIXED_POLICY_ACCOUNT_AUTHORITY_V1",
        scientific_identity="FULL_SELECTOR_FIXED_POLICY_RESEARCH_ACCOUNT",task_id=ID,
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY",accounting_clock_convention=source.CLOCK,
        scope_start="2023-01-01",scope_end_exclusive="2026-01-01",strict_PIT_promotion_eligible=False,
        production_qualified=False,quote_qualified=False,certified_NAV=False,
        frozen_contract_ref=dict(contract_ref),event_fingerprints=[e.event_fingerprint for e in retained],
        ordinary_cash_event_fingerprints=sorted(ordinary),frozen_history_cash_admission=admission,
        terminal_source_authority=terminal_authority)
    ca._validate_research_account_authority(tuple(retained),authority)
    b.update(entitlement_events=tuple(retained),entitlement_security_tickers=tickers,
        entitlement_enabled=True,research_account_authority=authority,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",
            source_fingerprint=digest(manifest),quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
            event_fingerprints=[e.event_fingerprint for e in retained],security_tickers=tickers,manifest=manifest))
    return b,manifest


def _load_python(ref,name):
    """Load pinned pure source with standard module registration for dataclasses."""
    import sys
    require(sha256(ref["path"])==ref["sha256"], "PINNED_PYTHON_SOURCE_CHANGED")
    spec=importlib.util.spec_from_file_location(name,ref["path"])
    require(spec is not None and spec.loader is not None, "PINNED_PYTHON_SOURCE_SPEC_REQUIRED")
    module=importlib.util.module_from_spec(spec);previous=sys.modules.get(name)
    sys.modules[name]=module
    try:spec.loader.exec_module(module)
    except BaseException:
        if previous is None:sys.modules.pop(name,None)
        else:sys.modules[name]=previous
        raise
    return module


def metadata_preflight(run):
    reader=FullSelectorReader(run)
    freeze_ref={"path":str(reader.run/"DESIGN_FREEZE.json"),"sha256":sha256(reader.run/"DESIGN_FREEZE.json")}
    freeze=json.loads(Path(freeze_ref["path"]).read_text(encoding="utf-8"))
    cfg=reader.manifest["account_inputs"]
    require(set(cfg)=={"sources","legacy_source_transport"} and cfg["sources"]==DEFAULT_REFS
        and freeze["account_inputs"]==cfg and freeze["account_config"]==ACCOUNT,
        "EXACT_FROZEN_ACCOUNT_INPUTS_REQUIRED")
    pin,read=custody_reader(cfg["legacy_source_transport"])
    for ref in (*DEFAULT_REFS.values(),*OWNERS.values()):pin(ref)
    sources=read(DEFAULT_REFS["ordinary_sources"])
    qb=read(DEFAULT_REFS["quote_binding"])
    for ref in sources["source_refs"]:pin(ref)
    require(isinstance(qb["source_refs"],dict),"QUOTE_NAMED_SOURCE_CLOSURE_REQUIRED")
    for ref in qb["source_refs"].values():pin(ref)
    for key in ("shared_rule_ref","parent_A_source_binding_ref","terminal_catalogue_ref",
                "quality_origin_and_defect_scope_ref","B_raw_coordinate_proof_ref"):
        pin(qb[key])
    calendar_ref=reader.manifest["input_sources"]["calendar"]
    guard_parquet(calendar_ref["path"],calendar_ref["sha256"],["trade_date"])
    calendar=pd.DatetimeIndex(pd.read_parquet(calendar_ref["path"],columns=["trade_date"]).trade_date)
    calendar=calendar[(calendar>="2023-01-01")&(calendar<"2026-01-01")]
    require(len(calendar)==752 and not calendar.has_duplicates and calendar.is_monotonic_increasing,
        "EXACT_752_ACCOUNT_CALENDAR_REQUIRED")
    keys=reader.keys.loc[reader.keys.signal_date.isin(calendar)].copy()
    identity_file,_=guard_parquet(DEFAULT_REFS["dated_identity"]["path"],
        DEFAULT_REFS["dated_identity"]["sha256"],["signal_date"])
    dated=identity_file.read(columns=["signal_date","ticker","security_id","moomoo_transport_code"]).to_pandas()
    dated.signal_date=pd.to_datetime(dated.signal_date)
    dated=dated.loc[dated.signal_date.isin(calendar)]
    links,gaps=identity_links(keys,read(DEFAULT_REFS["a_mapping"]),read(DEFAULT_REFS["a_identity"]),dated)
    # Preserve the whole model U even when an account-only source fact is missing.
    # Actual chosen/held/filled keys are checked by the finite account caller.
    raw_keys=dated[["signal_date","ticker","security_id"]].rename(columns={"security_id":"cusip"}).copy()
    raw_keys["security_uid"]="CUSIP:"+raw_keys.cusip.astype(str).str.strip().str.upper()
    raw_links,raw_gaps=identity_links(raw_keys,read(DEFAULT_REFS["a_mapping"]),read(DEFAULT_REFS["a_identity"]),dated)
    # Physical hashes and time metadata pass before any raw price projection.
    raw,_=guard_parquet(DEFAULT_REFS["raw_prices"]["path"],DEFAULT_REFS["raw_prices"]["sha256"],["trade_date"])
    require(set(("ticker","trade_date","open","close")).issubset(raw.schema.names),"RAW_OPEN_CLOSE_SCHEMA_REQUIRED")
    return dict(reader=reader,freeze=freeze,freeze_ref=freeze_ref,pin=pin,read=read,
        calendar=calendar,keys=keys,identity_links=links,identity_gaps=gaps,
        raw_identity_links=raw_links,raw_identity_gaps=raw_gaps,ordinary_sources=sources,
        quote_binding=qb,raw_file=raw,source_gaps=sources["unresolved_source_gaps"])


def load_account_inputs(run):
    """Actual input entry; caller authorization/freeze precedes first price decode."""
    bound=metadata_preflight(run);pin,read=bound["pin"],bound["read"]
    gate=json.loads((bound["reader"].run/"FREEZE_ACCEPTANCE.json").read_text(encoding="utf-8"))
    require(gate.get("status")=="PASS" and gate.get("design_sha256")==bound["freeze_ref"]["sha256"]
        and gate.get("input_manifest_sha256")==sha256(bound["reader"].run/"input_manifest.json"),
        "INDEPENDENT_ACCOUNT_FREEZE_ACCEPTANCE_REQUIRED_BEFORE_PRICE_READ")
    original=joblib.load(pin(DEFAULT_REFS["original_cash_kwargs"]))
    require(not {"market","mu","sigma","feature_cube","predictions"} & set(original),
        "SOURCE_KWARGS_ONLY_NO_ACCOUNT_OR_FORECAST_CACHE")
    # Transport only the three declared original base entitlement class layouts.
    if original["entitlement_events"] and type(original["entitlement_events"][0]) is not ca.SourceBackedEntitlementEvent:
        import sys
        old=sys.modules[type(original["entitlement_events"][0]).__module__]
        original=source.rebind_entitlement_catalogue(original,source_owner=old,target_owner=ca)
    owner=SimpleNamespace(**vars(account));owner._frozen_ca_module=ca
    adapter=private_source_adapter(pin,read)
    descendant=adapter.bind_source_account_descendant(owner,original,bound["ordinary_sources"],
        account_dates=bound["calendar"],bundle_ref=DEFAULT_REFS["ordinary_sources"])
    old_authority=read(DEFAULT_REFS["a_authority"])["research_account"]["research_account_authority"]
    events,composition=combine_cash_and_terminal(descendant,
        _typed_a(read(DEFAULT_REFS["a_catalogue"])["events"]),old_authority,bound["freeze_ref"])
    names=["ticker","trade_date","open","close"]
    if "price_quality_warning" in bound["raw_file"].schema.names:names.append("price_quality_warning")
    prices=bound["raw_file"].read(columns=names).to_pandas()
    prices.trade_date=pd.to_datetime(prices.trade_date)
    prices=prices.loc[prices.trade_date.isin(bound["calendar"])]
    market_adapter=_load_python(DEFAULT_REFS["market_adapter"],"_full_selector_existing_market")
    market=market_adapter.make_market(account,prices,bound["keys"],bound["calendar"])
    composer=_load_python(DEFAULT_REFS["quote_composer"],"_full_selector_existing_quote_composer")
    market=composer.bind_original_wrapper_quality(market,original)
    classified=read(DEFAULT_REFS["quote_classification"])
    usable,coverage=quote.build_usable_a_mask(market.dates,market.tickers,market.quality,
        classified["branches"]["A"]["decisions"],raw_open=market.open,raw_close=market.close)
    bound.update(market=market,events=events,composer=composer,usable_a=usable,
        quote_coverage=coverage,cash_source_receipt=descendant["receipt"],source_composition=composition)
    return bound
