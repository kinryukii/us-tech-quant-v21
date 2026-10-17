"""Fixed Top20 caller for the single continuous research-account owner."""
from __future__ import annotations
import copy
from types import FunctionType, SimpleNamespace
import numpy as np
import pandas as pd
from scripts.research.a2.data.full_selector_account_inputs import ACCOUNT, FRICTION, ID, require, digest
from scripts.research.a2.evaluation import continuous_research_account as account
from scripts.research.a2.evaluation import joint_frozen_history_r3 as snapshot


def membership_policy(keys,membership,path_ids,calendar):
    """Membership-only weights. All locks, sells, buys and costs belong to the owner."""
    ids=tuple(path_ids)
    require(ids and len(ids)<=66 and len(set(ids))==len(ids),"FINITE_UNIQUE_ACCOUNT_PATHS_REQUIRED")
    require({"path_id","signal_date","security_uid","ticker","rank"}.issubset(membership.columns),
        "FROZEN_FULL_U_MEMBERSHIP_SCHEMA_REQUIRED")
    f=membership[["path_id","signal_date","security_uid","ticker","rank"]].copy()
    f.signal_date=pd.to_datetime(f.signal_date)
    require(set(f.path_id)==set(ids) and f.signal_date.isin(calendar).all()
        and not f.duplicated(["path_id","signal_date","security_uid"]).any()
        and not f.duplicated(["path_id","signal_date","ticker"]).any(),
        "UNIQUE_FROZEN_ACCOUNT_MEMBERSHIP_REQUIRED")
    rank=pd.to_numeric(f["rank"],errors="raise")
    require(np.isfinite(rank).all() and rank.eq(np.floor(rank)).all() and rank.ge(1).all(),
        "POSITIVE_INTEGER_SELECTION_RANK_REQUIRED")
    f["rank"]=rank
    joined=f.merge(keys[["signal_date","security_uid","ticker"]],on=["signal_date","security_uid"],
        how="left",suffixes=("","_source"),validate="many_to_one")
    require(joined.ticker.eq(joined.ticker_source).all(),"SELECTION_OUTSIDE_EXACT_DATED_FULL_U")
    f=f.loc[f["rank"].le(20)]
    universe=keys.groupby("signal_date").size()
    selected={}
    groups={(p,pd.Timestamp(d)):g for (p,d),g in f.groupby(["path_id","signal_date"],sort=False)}
    empty=f.iloc[:0]
    for path in ids:
        for day in calendar:
            group=groups.get((path,pd.Timestamp(day)),empty)
            n=min(20,int(universe.get(day,0)))
            require(len(group)==n and set(group["rank"])==set(range(1,n+1)),
                "COMPLETE_MIN20_FULL_U_SELECTION_REQUIRED:"+str(path)+":"+str(day.date()))
            selected[(path,pd.Timestamp(day))]=tuple(group.sort_values("rank").ticker)
    def policy(index,ctx):
        require(tuple(ctx.path_ids)==ids,"ACCOUNT_AXIS_CHANGED")
        weights=np.zeros((len(ids),len(ctx.tickers)),float)
        ti={str(t):i for i,t in enumerate(ctx.tickers)}
        for r,path in enumerate(ids):
            for ticker in selected[(path,pd.Timestamp(ctx.signal_date))]:
                require(ticker in ti,"SELECTED_NAME_OUTSIDE_RAW_MARKET_AXIS")
                weights[r,ti[ticker]]=.05
        # Explicit exits include held names outside today's U; unavailable names
        # stay locked under the existing owner. No filtering/renormalization here.
        return account.TargetDecision(weights=weights,
            explicit_mask=np.asarray(ctx.decision_mask,bool).copy(),
            raw_evidence_id="FULL_U_FIXED_TOP20_EQUAL_WEIGHT_5PCT")
    return policy


def qualify_research_account(replay,bound,path_ids):
    """Reuse the original independent raw snapshot with an explicit research view.

    The only waived strict exception is the already-authorized exact original
    MKFG unknown-settlement receivable. Its value stays nonspendable and strict
    account/production flags remain false.
    """
    actual=pd.concat([
        replay.positions.loc[replay.positions.fractional_shares.gt(1e-10),["date","ticker"]].rename(columns={"date":"signal_date"}),
        replay.fills[["execution_date","ticker"]].rename(columns={"execution_date":"signal_date"})],ignore_index=True)
    links=bound["raw_identity_links"][["signal_date","ticker","accounting_sid"]]
    actual=actual.merge(links,on=["signal_date","ticker"],how="left",validate="many_to_one")
    require(actual.accounting_sid.notna().all(),"ACTUAL_HELD_OR_FILLED_DATED_IDENTITY_SOURCE_GAP")
    view=copy.copy(replay)
    view.daily=replay.daily.copy()
    require("research_accounting_qualified" in view.daily,"RESEARCH_ACCOUNT_QUALIFICATION_REQUIRED")
    view.daily["original_strict_accounting_qualified"]=view.daily.accounting_qualified
    view.daily["accounting_qualified"]=view.daily.research_accounting_qualified
    original_exceptions=replay.accounting_exceptions.copy()
    view.accounting_exceptions=original_exceptions.copy()
    terminals=[e for e in bound["events"]["entitlement_events"]
        if isinstance(e,account.SourceBackedTerminalEvent)]
    require(len(terminals)==1 and terminals[0].ticker=="MKFG" and terminals[0].settlement is None,
        "EXACT_MKFG_UNKNOWN_SETTLEMENT_REQUIRED")
    event=terminals[0];allowed=[]
    if not original_exceptions.empty:
        allowed=(original_exceptions.reason.eq("TERMINAL_SETTLEMENT_AUTHORITY_MISSING")
            & original_exceptions.event_id.eq(event.event_id)
            & original_exceptions.ticker.eq(event.ticker)
            & original_exceptions.event_fingerprint.eq(event.event_fingerprint))
        view.accounting_exceptions=original_exceptions.loc[~allowed].copy()
    for name in ("positions","orders","fills","execution_results","contexts","operational_actions","entitlements"):
        if hasattr(view,name):setattr(view,name,getattr(view,name).copy())
    view.metadata=copy.deepcopy(replay.metadata)
    original_execution=replay.execution_results.copy()
    effect=account._entitlement_effective_day(event)
    cancelled=(view.execution_results.status.eq("REJECTED")
        & view.execution_results.reason.eq("MISSING_PRICE_ROW")
        & view.execution_results.ticker.eq(event.ticker)
        & pd.to_datetime(view.execution_results.execution_date).eq(effect)
        & pd.to_datetime(view.execution_results.signal_date).lt(effect))
    # Original owner closes the security before pending orders execute. Such
    # exact zero-fill cancellations are not missing economic execution inputs.
    for row in view.execution_results.loc[cancelled].itertuples():
        state=replay.final_state["entitlement_states"][list(replay.metadata["path_ids"]).index(row.path_id)]
        quantities=dict(state.ex_quantities)
        require(event.event_id in quantities and quantities[event.event_id]>=0
            and row.notional==0 and row.index_units==0 and row.transaction_cost==0,
            "TERMINAL_CANCEL_EXACT_ZERO_FILL_AND_LIFECYCLE_REQUIRED")
        held=view.positions.loc[view.positions.path_id.eq(row.path_id)
            & view.positions.ticker.eq(event.ticker) & pd.to_datetime(view.positions.date).ge(effect)]
        filled=view.fills.loc[view.fills.path_id.eq(row.path_id)
            & view.fills.ticker.eq(event.ticker) & pd.to_datetime(view.fills.execution_date).ge(effect)]
        require(not held.fractional_shares.gt(1e-10).any() and filled.empty,
            "TERMINAL_CANCEL_SECURITY_REAPPEARED_OR_FILLED")
        if quantities[event.event_id]>0:
            extinct=view.entitlements.loc[view.entitlements.path_id.eq(row.path_id)
                & view.entitlements.event_id.eq(event.event_id)
                & view.entitlements.phase.eq("SECURITY_EXTINGUISHED")]
            require(len(extinct)==1 and extinct.event_fingerprint.eq(event.event_fingerprint).all()
                and extinct.remaining_raw_shares.eq(0).all(),
                "TERMINAL_CANCEL_EXACT_EXTINGUISHMENT_REQUIRED")
    view.execution_results.loc[cancelled,"reason"]="TERMINAL_SECURITY_EXTINGUISHED"
    freeze=SimpleNamespace(path_ids=tuple(path_ids),research_id=ID,
        parent_research_id="EXACT_SOURCE_AND_CONTINUOUS_ACCOUNT_OWNER_REUSE",
        run_id=bound["reader"].run.name,research_kind="FULL_SELECTOR_FIXED_POLICY_RESEARCH_ACCOUNT",
        identity_assumption="Full-U original CUSIP plus unique dated original raw-share accounting map",
        synthetic=False,digest=lambda:digest(bound["freeze"]))
    fn=snapshot._qualify
    ns=dict(fn.__globals__,_audit_pass=bound["composer"].audit_pass)
    qualify=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__)
    qualify.__kwdefaults__=fn.__kwdefaults__
    receipt=qualify(view,bound["market"],bound["usable_a"],freeze,{p:[] for p in path_ids})
    # Restore the retained original strict flags and exception ledger after the
    # independent research projection; this is not certified NAV promotion.
    view.daily["accounting_qualified"]=view.daily.original_strict_accounting_qualified
    view.accounting_exceptions=original_exceptions
    view.execution_results=original_execution
    view.daily["TOTAL_ECONOMIC_NAV"]=view.daily.mechanism_account_value
    rights=view.daily.get("receivable_value_usd",pd.Series(0.,index=view.daily.index))
    view.daily["LIQUID_NAV"]=view.daily.TOTAL_ECONOMIC_NAV-rights
    for path in path_ids:
        f=view.daily.loc[view.daily.path_id.eq(path)]
        complete=(len(f)==len(bound["calendar"]) and
            pd.DatetimeIndex(f.date).equals(bound["calendar"]))
        q=receipt[path]
        q.update(full_window_complete=complete,unknown_terminal_nonspendable=True,
            strict_accounting_qualified=bool(f.accounting_qualified.all()),
            dual_nav_scope="current source-bound raw Close outcome; unchanged decision/engine indicative NAV")
        require(complete and q["mechanism_accounting_consistent"]
            and np.isfinite(f[["TOTAL_ECONOMIC_NAV","LIQUID_NAV"]].to_numpy(float)).all(),
            "FULL_WINDOW_ACCOUNT_QUALIFICATION_FAILED:"+str(path))
    view.metadata["exact_unknown_terminal_exception_projection"]={
        "event_id":event.event_id,"event_fingerprint":event.event_fingerprint,
        "exception_rows":int(sum(allowed)) if len(allowed) else 0,
        "exact_pre_effective_zero_fill_cancel_rows":int(cancelled.sum()),
        "original_execution_results_retained":True,
        "original_exception_ledger_retained":True,"receivable_spendable":False}
    return view,receipt


def run_fixed_accounts(bound,membership,path_ids,*,ledger_callback=None,on_backend=None):
    """One actual call into the existing owner; caller controls the finite ledger."""
    ids=tuple(path_ids);declared=tuple(bound["freeze"]["account_path_ids"])
    require(len(declared)<=66 and len(set(declared))==len(declared)
        and set(ids).issubset(declared),"FROZEN_66_ACCOUNT_NAMESPACE_REQUIRED")
    chosen=membership.loc[membership["rank"].le(20),["signal_date","security_uid","ticker"]]
    identity=chosen.merge(bound["identity_links"][["signal_date","security_uid","ticker","accounting_sid"]],
        on=["signal_date","security_uid","ticker"],how="left",validate="many_to_one")
    require(identity.accounting_sid.notna().all(),"SELECTED_PATH_DATED_IDENTITY_SOURCE_GAP")
    policy=membership_policy(bound["keys"],membership,ids,bound["calendar"])
    proofs=[]
    owner=bound["composer"].adapt_owner(account,bound["usable_a"],proofs)
    if on_backend is not None:on_backend()
    replay=owner.run_continuous_account(bound["market"],ids,policy,copy.deepcopy(ACCOUNT),
        execution_friction=dict(FRICTION),ledger_callback=ledger_callback,**bound["events"])
    # Preserve the actual completed owner's non-streamed ledgers before any
    # source/account qualification failure can raise. Values remain original.
    if ledger_callback is not None:
        for name in ('entitlements','accounting_exceptions'):
            ledger_callback(name,getattr(replay,name))
    replay,receipt=qualify_research_account(replay,bound,ids)
    proof=pd.concat(proofs,ignore_index=True) if proofs else pd.DataFrame()
    replay.metadata.update(account_input_sources=bound["reader"].manifest["account_inputs"],
        account_source_gaps=bound["source_gaps"],account_source_gap_scope="source population; actual held/executed facts require full-window qualification",
        independent_qualification=receipt,finite_account_path_ids=list(declared))
    return replay,receipt,proof
