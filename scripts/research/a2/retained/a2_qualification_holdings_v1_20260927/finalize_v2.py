"""Assemble already completed versioned results without refitting or replay."""
from pathlib import Path
import json
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'a2_latest_effective_joint_20260927'


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    folders=[ROOT/'evaluation_2025/cost_10']+[ROOT/f'evaluation_2026/cost_{c}' for c in [10,5,25]]
    assert all((p/'COMPLETE.json').exists() for p in folders)
    comparisons=pd.concat([pd.read_csv(p/'comparison.csv') for p in folders],ignore_index=True)
    assert len(comparisons)==54
    comparisons.to_csv(ROOT/'ALL_VERSIONED_SCENARIOS.csv',index=False,encoding='utf-8-sig')
    panel=pd.read_parquet(ROOT/'data/test_features_context.parquet')
    prices=pd.read_parquet(ROOT/'data/test_prices.parquet')
    old=pd.read_csv(OLD/'LAST_TEST_DATE_TARGETS.csv',dtype={'cusip':str})
    old=old.loc[old[['quarter','cusip','new_buy_eligible']].isna().any(axis=1)].copy()
    day=pd.Timestamp('2026-09-22');execution=pd.Timestamp('2026-09-23')
    pc=panel.loc[panel.signal_date.eq(day)].set_index('ticker')
    px=prices.loc[prices.trade_date.eq(execution)].set_index('ticker')
    events=pd.read_parquet(ROOT/'evidence/events/security_day_qualification.parquet')
    ed=events.loc[events.date.eq(day)].set_index('ticker')
    iddata=read(ROOT/'evidence/identity/identity_lifecycle_qualification.json')
    ident={r['ticker']:r for r in iddata['securities']}
    mapped=[]
    for r in old.itertuples():
        f=pc.loc[r.ticker] if r.ticker in pc.index else None
        q=px.loc[r.ticker] if r.ticker in px.index else None
        lifecycle=r.ticker=='EXAS'
        state='OPERATIONAL_EXIT_REQUIRED_SETTLEMENT_UNKNOWN' if lifecycle else (
            'INPUT_AND_EXECUTION_PRICE_QUALIFIED' if f is not None and q is not None and not bool(q.price_quality_warning)
            else 'MODEL_NO_DECISION_QUALIFICATION_REMAINS_UNKNOWN')
        mapped.append(dict(old_policy=r.policy,ticker=r.ticker,signal_date=str(day.date()),execution_date=str(execution.date()),
            shared_event_instrument_key=ed.loc[r.ticker,'instrument_key'],event_prefix_status=ed.loc[r.ticker,'status'],
            input_present=f is not None,context_only_if_held=bool(f.context_only_if_held) if f is not None else None,
            new_buy_eligible=bool(f.new_buy_eligible) if f is not None else None,
            price_row_present=q is not None,execution_price_qualified=(not bool(q.price_quality_warning)) if q is not None else False,
            identity_state=ident[r.ticker]['state'],qualification_outcome=state,
            old_current_weight=r.current_weight,old_indicative_value=r.current_weight*r.signal_close_nav,
            note='Mapping of original cases to shared data evidence; not a claim that a newly trained account holds the same stock or executed an exit.'))
    mapping=pd.DataFrame(mapped)
    assert len(mapping)==54 and mapping.ticker.nunique()==45
    assert mapping.groupby('ticker').event_prefix_status.nunique().max()==1
    mapping.to_csv(ROOT/'LEGACY54_QUALIFICATION_MAPPING.csv',index=False,encoding='utf-8-sig')
    latest=[];states=[]
    for folder in sorted((ROOT/'evaluation_2026/cost_10').iterdir()):
        if not folder.is_dir():continue
        t=pd.read_parquet(folder/'target_decisions.parquet')
        ex=pd.read_parquet(folder/'execution_results.parquet')
        held=t.current_units.gt(0)
        states.append(dict(policy=folder.name,model_active_exit=int((held&t.decision_semantic.eq('MODEL_ACTIVE_EXIT')).sum()),
            model_no_decision=int((held&t.decision_semantic.eq('MODEL_NO_DECISION')).sum()),
            operational_exit_required=int((held&t.decision_semantic.eq('OPERATIONAL_EXIT_REQUIRED')).sum()),
            execution_rejected=int(ex.status.eq('REJECTED').sum())))
        last=t[t.signal_date.eq(day)&(held|t.target_weight.gt(0))].copy()
        # Only the last signal is joined below; do not aggregate all earlier zero orders.
        last_execution=ex.loc[ex.order_id.isin(last.order_id)]
        outcome=last_execution.groupby('order_id').agg(execution_status=('status',lambda a:'|'.join(sorted(set(a)))),
            execution_reason=('reason',lambda a:'|'.join(sorted(set(a.dropna().astype(str)))))).reset_index()
        last=last.merge(outcome,on='order_id',how='left',validate='one_to_one')
        latest.append(last)
    pd.concat(latest,ignore_index=True).to_csv(ROOT/'LAST_SIGNAL_DECISIONS.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(states).to_csv(ROOT/'DECISION_STATE_COUNTS.csv',index=False,encoding='utf-8-sig')
    print(json.dumps(dict(scenarios=len(comparisons),legacy_mapping=len(mapping),legacy_status=mapping.qualification_outcome.value_counts().to_dict(),
        completed=True),ensure_ascii=False))


if __name__=='__main__':main()
