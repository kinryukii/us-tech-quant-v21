"""R6 Gross supervision/execution over the one guarded opportunity reader."""
from pathlib import Path
import argparse,os
import joblib
import numpy as np
import pandas as pd
from scripts.research.a2.training import joint_method_space_gross_r6 as g
from scripts.research.a2.training import joint_method_space_opportunity_execution_r6 as io
from scripts.research.a2.evaluation import joint_method_space_runtime_r6 as rt
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as parent
from scripts.research.a2.training import stateful_mechanism_models as native

YEARS=(2023,2024,2025)
LEARNED='estimator_learned_state_fit'
REF_FEATURES=('realized_vol_20d','downside_vol_20d','avg_dollar_volume_20d')

def specification():
    return dict(schema='B_R6_GROSS_EXECUTION_V1',recipes=g.recipes(),years=YEARS,
        packet='EXACT_GENUINE_R4_EQUAL_COMPLETE_FIVE_MEMBERS',
        uncertainty='3 ANNUAL STRICTLY_EARLIER_GENUINE_R4_EQUAL_ERROR_RMS; NO NATIVE_DISTRIBUTION_CLAIM',
        rms_states_upper=3,learned_components_upper=24,
        reference_maturity='top20 selected on complete structural alpha before labels; only mechanically immature endpoint dates excluded; unknown or unsupported selected targets block whole fold, never replace with labeled next name',scientific_retry=0,
        input='same Source predicate/key/UID/support guard; no second reader/platform',
        forecast_role='CURRENT_ELIGIBLE_ALPHA_OOF; NOT FULL_HELD_POLICY_QUALIFICATION')

def _save(run,relative,value):
    target=run/relative
    if target.exists():raise ValueError('IMMUTABLE_GROSS_ARTIFACT_ALREADY_PRESENT')
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix(target.suffix+'.writing')
    if temp.exists():raise ValueError('INCOMPLETE_GROSS_ARTIFACT_REQUIRES_ENGINEERING_REVIEW')
    joblib.dump(value,temp)
    with temp.open('r+b') as handle:os.fsync(handle.fileno())
    os.replace(temp,target)

def reference_rows(source,*,start,stop,mature):
    keys=source.rows(start=start,stop=stop,alpha=True)
    if keys.empty:raise ValueError('NO_GROSS_SOURCE_QUALIFIED_REFERENCE_DOMAIN')
    parts=[]
    for year,group in keys.groupby(keys.signal_date.dt.year,sort=True):
        if year not in (2022,2023,2024,2025):continue
        packet=io.r4_equal_packet(source,int(year),group)
        if packet.attrs.get('verified_full_five_member_genuine_clocks') is not True or not {'verified_source_fit_cutoff','verified_source_label_mature_max','genuine_chronological_oof'}.issubset(packet):raise ValueError('REAL_FIVE_MEMBER_GENUINE_CLOCK_RECEIPTS_REQUIRED')
        packet['fit_cutoff']=pd.to_datetime(packet.verified_source_fit_cutoff,utc=True).dt.tz_convert(None)
        if not (pd.to_datetime(packet.verified_source_label_mature_max,utc=True).dt.tz_convert(None)<packet.fit_cutoff).all():raise ValueError('REAL_PRODUCER_MATURITY_CUTOFF_REQUIRED')
        verified=dict(packet.attrs)
        context=source.context(group,stop,columns=REF_FEATURES)
        packet=packet.merge(context,on=io.KEYS,how='left',validate='one_to_one')
        packet.attrs.update(verified)
        packet['mu']=packet.native_equal_mu.to_numpy(float)
        # Selection precedes every target/maturity restriction. Never replace
        # a selected unsupported stock with the next name that has a label.
        selected=[]
        for day,domain in packet.groupby('signal_date',sort=True):
            ref=domain.sort_values(['mu','ticker'],ascending=[False,True],kind='stable').head(20)
            if len(ref)!=20:raise ValueError('FIXED_TOP20_REFERENCE_DOMAIN_INCOMPLETE')
            if mature:
                clocks=[pd.to_datetime(ref[c]) for c in ('execution_date','label_end_date','label_mature_date')]
                if any(x.isna().any() for x in clocks):raise ValueError('UNKNOWN_REFERENCE_MATURITY_NO_DATE_DROP')
                if any(not (x<pd.Timestamp(stop)).all() for x in clocks):continue # strictly frozen maturity boundary only
                ref=ref.copy();ref['y_open5']=source.truth(ref,stop)
            selected.append(ref)
        if selected:parts.append(pd.concat(selected,ignore_index=True))
    if not parts:raise ValueError('NO_GENUINE_R4_EQUAL_GROSS_DOMAIN')
    return pd.concat(parts,ignore_index=True)

def inference_reference(frame,rms):
    if not np.isfinite(rms) or rms<=0:raise ValueError('GENUINE_PRIOR_GROSS_ERROR_RMS_REQUIRED')
    rows=[]
    for day,domain in frame.groupby('signal_date',sort=True):
        values=domain[['mu',*REF_FEATURES]].to_numpy(float)
        if not np.isfinite(values).all():raise ValueError('FULL_GROSS_INFERENCE_DOMAIN_NONFINITE_NO_DROP')
        ref=domain.sort_values(['mu','ticker'],ascending=[False,True],kind='stable').head(20)
        if len(ref)!=20:raise ValueError('FIXED_TOP20_GROSS_INFERENCE_SUPPORT_REQUIRED')
        vol=ref.realized_vol_20d.to_numpy(float)
        rows.append(dict(signal_date=day,mean_mu=float(ref.mu.mean()),mean_sigma=rms,
            positive_mu_fraction=float((ref.mu>0).mean()),diagonal_vol_proxy_5d=float(np.sqrt(5*np.square(vol).sum()/400)),
            mean_liquidity=float(ref.avg_dollar_volume_20d.mean()),mean_downside_vol20=float(ref.downside_vol_20d.mean()),vol20_dispersion=float(np.std(vol))))
    return pd.DataFrame(rows)

def run(run,freeze_sha):
    run=rt.guard_numeric(run,freeze_sha)
    with rt.stage_writer(run,'gross'):
        if (run/'work/R6_GROSS_EXECUTION_RECEIPT.json').exists():raise ValueError('IMMUTABLE_GROSS_EXECUTION_RECEIPT_NO_REPLAY')
        source=io.Source(run,freeze_sha);ledger=rt.R6Ledger(run,freeze_sha);results=[]
        for year in YEARS:
            cutoff=f'{year}-01-01';end=f'{year+1}-01-01';nodes=[]
            try:
                train=reference_rows(source,start='2022-01-01',stop=cutoff,mature=True)
                node=f'GROSS:R4_EQUAL_PRIOR_RMS:{year}'
                ledger.reserve(LEARNED,node,physical_kind='genuine prior OOF RMS');nodes.append(node)
                rms=float(np.sqrt(np.mean(np.square(train.y_open5.to_numpy(float)-train.mu.to_numpy(float)))))
                if not np.isfinite(rms) or rms<=0:raise ValueError('NONFINITE_GROSS_PRIOR_ERROR_RMS')
                ledger.complete(node,rows=len(train),cutoff=cutoff,value_role='UNCALIBRATED_NATIVE_OOF_ERROR_SCALE')
                train['sigma']=rms
                supervision=g.aggregate_reference(train,cutoff)
                infer=reference_rows(source,start=cutoff,stop=end,mature=False)
                states=inference_reference(infer,rms)
                scaler_node=f'GROSS:SCALER:{year}'
                def scale_start(component):
                    ledger.reserve(LEARNED,scaler_node,physical_kind=component);nodes.append(scaler_node)
                scaler,scale_meta=native.fit_weighted_scaler(supervision[list(g.FEATURES)].to_numpy(float),{'weights':np.ones(len(supervision))},on_fit_started=scale_start)
                ledger.complete(scaler_node,rows=len(supervision),metadata=scale_meta)
                x=scaler.transform(supervision[list(g.FEATURES)].to_numpy(float));test=scaler.transform(states[list(g.FEATURES)].to_numpy(float))
                _save(run,f'models/gross/{year}_shared.joblib',dict(scaler=scaler,prior_rms=rms,source_sha256=parent.sha(run/'SOURCE_AUTHORITY.json'),freeze_sha256=freeze_sha))
            except Exception as exc:
                for node in nodes:
                    row=next(e for e in ledger.status['physical_events'] if e['node_id']==node)
                    if row['status']=='STARTED':ledger.fail(node,error=type(exc).__name__,reason=str(exc))
                for kind in g.FAMILIES:results.append(dict(year=year,method=kind,status='BLOCKED_INPUT',reason=str(exc),actual_fit=0))
                continue
            for kind in g.FAMILIES:
                node=f'GROSS:{kind}:{year}';started=False
                try:
                    def fit_start(component):
                        nonlocal started
                        if started:raise ValueError('UNFROZEN_ADDITIONAL_GROSS_BACKEND')
                        ledger.reserve(LEARNED,node,2 if kind=='MLP' else 1,physical_kind=component);started=True
                    fitted,meta=g.fit(kind,x,supervision.target.to_numpy(float),np.ones(len(x)),dates=supervision.signal_date,mature_dates=supervision.label_mature_date,cutoff=cutoff,dependencies=(io.EXTRA,),on_fit_started=fit_start)
                    if not started:raise ValueError('NATIVE_GROSS_FIT_ACK_REQUIRED')
                    ledger.complete(node,backend_calls=meta['actual_fit_count'],metadata=meta)
                    _save(run,f'models/gross/{kind}_{year}.joblib',fitted)
                    prediction=g.predict(fitted,test)
                    out=states[['signal_date']].copy();out['gross']=prediction;out['method']=kind;out['fit_cutoff']=cutoff
                    out['strict_PIT_promotion_eligible']=False;out['full_held_policy_qualified']=False
                    target=run/f'predictions/gross/{kind}_{year}.parquet';target.parent.mkdir(parents=True,exist_ok=True)
                    if target.exists():raise ValueError('IMMUTABLE_GROSS_PREDICTION_ALREADY_PRESENT')
                    out.to_parquet(target,index=False)
                    results.append(dict(year=year,method=kind,status='TRIED_COMPLETE',fit_node=node,predictions_ref=io.ref(target),output_role='CURRENT_ELIGIBLE_ALPHA_OOF'))
                except Exception as exc:
                    if started:
                        row=next(e for e in ledger.status['physical_events'] if e['node_id']==node)
                        if row['status']=='STARTED':ledger.fail(node,error=type(exc).__name__,reason=str(exc))
                    results.append(dict(year=year,method=kind,status='TRIED_FAILED' if started else 'BLOCKED_INPUT',reason=str(exc),fit_node=node if started else None))
        receipt=dict(research_id=io.ID,stage='gross',results=results,scientific_retry=0,test2026_reads=0)
        parent.write(run,'work/R6_GROSS_EXECUTION_RECEIPT.json',receipt)
        return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--freeze-sha',required=True);a=p.parse_args()
    result=run(Path(a.run),a.freeze_sha);print({'stage':result['stage'],'slots':len(result['results'])})
