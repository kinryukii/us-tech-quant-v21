"""R6 thin source qualification and fixed opportunity/fusion execution.

Original B/R3 physical guards, R5 metadata cursor/index code, native fit ACK and
R6 single ledger are reused. Import and prepare never read numeric values.
No R5 results, identity carry, hidden domain trimming, or account engine.
"""
from __future__ import annotations
import argparse
from types import SimpleNamespace
import gc
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import joblib
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import joint_method_space_opportunity_r6 as model
from scripts.research.a2.training import joint_opportunity_execution_r4 as old_training
from scripts.research.a2.training import stateful_values as fit_owner
from scripts.research.a2.training import stateful_mechanism_models as mechanism
from scripts.research.a2.evaluation import joint_method_space_runtime_r6 as runtime
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as old
from scripts.research.a2.data import joint_event_risk_support_r5 as metadata_owner
from scripts.research.a2.data.joint_held_identity_completion_r5 import _metadata_projection
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.data.joint_input_binding import FEATURES, ACCEPTED_FEATURE_TAGS

ID=model.ID
REPO=model.REPO
KEYS=['signal_date','ticker']
META_REF='work/R6_SEQUENCE_IDENTITY_SUPPORT.json'
ROWS_REF='support/R6_SEQUENCE_IDENTITY_ROWS.parquet'
ALPHA_ROLE='CURRENT_ELIGIBLE_ALPHA_OOF'
POLICY_ROLE='FULL_REQUIRED_ELIGIBLE_PLUS_HELD_POLICY_OOF'
BINDING_SHA=old_training.OLD_BINDING_SHA
SOURCE_SHA='04d17931c7437f9c7bc1277b33820c52ec2e527a995b0f1c587dc26f5b2c2fd8'
SOURCE_NAMES=('prediction_features','calendar','uid_intervals')
LEARNED='estimator_learned_state_fit'
TORCH=Path('D:/us-tech-quant-envs/frozen_dependency_snapshots/development_contexts/fast3_minute_inventory_r1/fast3_torch_cpu/Lib/site-packages')
EXTRA=Path('D:/us-tech-quant-envs/frozen_dependency_snapshots/a2_predict_then_optimize_20260928_r1/third_party')

class Blocked(ValueError): pass

def ref(path):
    path=Path(path);return dict(path=str(path),sha256=old.sha(path),bytes=path.stat().st_size)

def source_binding(run):
    run=Path(run).resolve();paths=resolve(REPO)
    assert_safe_output_path(run,kind='backtest',paths=paths)
    if run.parent!=paths.backtest_root/'V24':raise Blocked('MANAGED_R6_RUN_REQUIRED')
    authority=old.read_json(run/'SOURCE_AUTHORITY.json')
    if authority.get('research_id')!=ID or authority.get('EF_access') is not False or authority.get('network_provider_fetch') is not False or authority.get('test2026_reads')!=0 or authority.get('R5_numeric_economic_read') is not False:
        raise Blocked('R6_METADATA_AUTHORITY_REQUIRED')
    if any(authority.get(k) is not False for k in ('strict_PIT_promotion_eligible','quote_qualified','certified_nav_qualified')):raise Blocked('MECHANISM_SOURCE_UNCERTIFIED_REQUIRED')
    source_path=old._safe_source(authority['source_inputs_ref'])
    if authority['source_inputs_sha256']!=SOURCE_SHA:raise Blocked('ORIGINAL_R3_SOURCE_REQUIRED')
    old._pin(source_path,SOURCE_SHA,'original_r3_sources')
    source=_metadata_projection(source_path,{'schema','sources','scientific_mode','strict_PIT_promotion_eligible','quote_qualified','certified_nav_qualified'})
    original=paths.results_root/'JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1'/'V24'/'INPUT_BINDING.json'
    old._pin(original,BINDING_SHA,'original_b_binding')
    binding=_metadata_projection(original,{'target','sources','extended_five_day_labels','own_held_feature_extension'})
    if binding.get('target')!=model.TARGET:raise Blocked('ORIGINAL_UNCLIPPED_B5D_TARGET_REQUIRED')
    pins=dict(panel=binding['sources']['accepted_five_day_panel'],label=binding['extended_five_day_labels'],raw_keys=binding['sources']['raw_prices'],held=binding['sources']['accepted_features'])
    if binding.get('own_held_feature_extension'):pins['held_extension']=binding['own_held_feature_extension']
    return run,source,pins,dict(source_inputs_ref=ref(source_path),target_binding_ref=ref(original),authority_ref=ref(run/'SOURCE_AUTHORITY.json'))

def metadata_reader(source):
    # Same physical guard body, narrowed named sources. No parent globals mutate.
    obj=old.ProjectedReader.__new__(old.ProjectedReader)
    constructor=mechanism._clone(old.ProjectedReader.__init__,{'SOURCE_NAMES':SOURCE_NAMES},lambda c:() if c==('qqq_qfq_years',) else c)
    constructor(obj,source,phase='support')
    return obj

def _known(v):
    return metadata_owner.known(v) and not str(v).upper().startswith(('UNKNOWN','TICKER_','HELD_'))

def qualify_rows(features,raw,intervals,panel,held,calendar):
    """Metadata only: all observed days precede source predicates/role filtering."""
    forbidden=set(model.FEATURES)|{'y_open5','raw_mu','Open','Close','open','close'}
    if any(forbidden.intersection(f.columns) for f in (features,raw,intervals,panel,held)):raise Blocked('METADATA_VALUES_FORBIDDEN')
    days=pd.DatetimeIndex(calendar)
    model._dates(pd.Series(days))
    if not days.is_unique or not days.is_monotonic_increasing:raise Blocked('EXACT_COMMON_CALENDAR_REQUIRED')
    features=features.copy();features.signal_date=model._dates(features.signal_date)
    raw=raw.copy();raw.signal_date=model._dates(raw.signal_date)
    panel=panel.copy();panel.signal_date=model._dates(panel.signal_date)
    held=held.copy();held.signal_date=model._dates(held.signal_date)
    if panel.duplicated(KEYS).any() or held.duplicated(KEYS).any():raise Blocked('FULL_UNCHANGED_REQUIRED_KEY_UNIQUENESS')
    intervals=intervals.copy()
    for name in ('effective_start','effective_end'):intervals[name]=model._dates(intervals[name])
    if intervals.effective_start.gt(intervals.effective_end).any():raise Blocked('BAD_IDENTITY_SOURCE_INTERVAL')
    intervals['_start']=intervals.effective_start;intervals['_end']=intervals.effective_end
    index=metadata_owner.CoordinateMetadataIndex(intervals)
    cursor=metadata_owner.MetadataPoolCursor(days)
    groups={pd.Timestamp(d):g for d,g in features.groupby('signal_date',sort=False)}
    raws={pd.Timestamp(d):g.rename(columns={'signal_date':'trade_date'}) for d,g in raw.groupby('signal_date',sort=False)}
    interval_groups={(a,u):g for (a,u),g in intervals.groupby(['ticker','security_id'],sort=False)}
    empty=features.iloc[:0];empty_raw=pd.DataFrame(columns=['ticker','trade_date','code'])
    records=[]
    for day in days:
        today=groups.get(day,empty);quotes=raws.get(day,empty_raw)
        pool=cursor.step(day,today,quotes)
        # All feature history rows receive the actual observed suffix; pool
        # membership is a separate structural flag, never a history filter.
        assets=tuple(sorted(set(today.ticker)))
        expanded=dict(pool,assets=assets,asset_uids={a:(cursor.suffix.get(a) or (None,None))[0] for a in assets})
        coords=index.lookup(expanded,day,quotes)
        # One batch interval projection per common day, equivalent to the
        # original repeated exact ticker/UID interval query for every row.
        fields=['security_id_type','cusip','title_of_class','moomoo_transport_code','mapping_status','report_quarter','quarter_universe_fingerprint']
        active=intervals.loc[intervals._start.le(day)&intervals._end.ge(day),['ticker','security_id',*fields]]
        declarations_by_key={}
        for values in active.itertuples(index=False,name=None):
            key=values[:2];record=tuple(None if pd.isna(v) else v for v in values[2:]);declarations_by_key.setdefault(key,set()).add(record)
        items={key:SimpleNamespace(**dict(zip(fields,next(iter(records))))) if len(records)==1 else None for key,records in declarations_by_key.items()}
        for row in today.itertuples(index=False):
            asset=row.ticker;uid=expanded['asset_uids'][asset];suffix=cursor.suffix.get(asset)
            coord=coords[asset];reason=None;epoch=None;start=None
            if suffix is not None:
                start=suffix[1].date().isoformat();epoch='OBSERVED_CONTIGUOUS_UID:'+content_hash(dict(asset=asset,uid=uid,start=start))
            if not _known(uid):reason='UNKNOWN_CURRENT_SECURITY_UID'
            elif asset in pool['blocked_assets']:reason=pool['blocked_assets'][asset]
            elif coord['class_coordinate_status']!='EXACT_FROZEN_INTERVAL_METADATA_DECLARATION':reason='NO_UNIQUE_EXACT_SECURITY_COORDINATE_INTERVAL'
            elif coord['mapping_status']!='RESOLVED' or coord['security_id_type']!='CUSIP' or not _known(coord['cusip']) or uid!=coord['cusip']:reason='UNBOUND_OR_CONFLICTING_SECURITY_NAMESPACE'
            elif not _known(coord['security_class_declaration']):reason='UNKNOWN_SECURITY_CLASS'
            item=items.get((asset,uid))
            if reason is None and item is None:reason='CONFLICTING_INTERVAL_DECLARATION'
            if reason is None and (len(coord['raw_transport_codes'])!=1 or item.moomoo_transport_code!=coord['raw_transport_codes'][0]):reason='RAW_SECURITY_TRANSPORT_COORDINATE_MISMATCH'
            source_ok=bool(row.feature_available is True and row.all_features_finite is True and row.feature_source in ACCEPTED_FEATURE_TAGS)
            records.append(dict(signal_date=day,ticker=asset,security_uid=uid,asset_epoch=epoch,segment_start=start,
                security_id_type=coord['security_id_type'],cusip=coord['cusip'],title_of_class=coord['security_class_declaration'],
                moomoo_transport_code=(item.moomoo_transport_code if item is not None else None),active_13f_quarter=(item.report_quarter if item is not None else None),quarter_universe_fingerprint=(item.quarter_universe_fingerprint if item is not None else None),
                identity_qualified=reason is None,source_qualified=source_ok,class_coordinate_status='EXACT_FROZEN_INTERVAL_COORDINATE_FOR_MECHANISM' if reason is None else coord['class_coordinate_status'],
                is_current_pool=asset in pool['assets'],feature_available=source_ok,block_reason=reason,
                same_uid_contiguous_sessions=(days.get_loc(day)-days.get_loc(suffix[1])+1 if suffix is not None else 0)))
    out=pd.DataFrame.from_records(records)
    # Duplicates preserve required keys as typed blocks, never choose first SID.
    duplicates=out.duplicated(KEYS,keep=False)
    if duplicates.any():
        bad=out.loc[duplicates,KEYS].drop_duplicates();out=out.loc[~duplicates]
        for c in out.columns:
            if c not in KEYS:bad[c]=False if c in ('identity_qualified','source_qualified','is_current_pool','feature_available') else None
        bad['block_reason']='AMBIGUOUS_FEATURE_IDENTITY_KEY';out=pd.concat([out,bad],ignore_index=True)
    original=panel[KEYS+old_training.IDENTITY+old_training.CLOCKS[1:]+['trade_eligible','fit_eligible']].rename(columns={c:'original_'+c for c in old_training.IDENTITY})
    wanted=out[KEYS].merge(original,on=KEYS,how='outer',validate='one_to_one',sort=False)
    wanted=wanted.merge(held.assign(is_required_held=True),on=KEYS,how='outer',validate='one_to_one',sort=False)
    out=wanted.merge(out,on=KEYS,how='left',validate='one_to_one',sort=False)
    for c in ('identity_qualified','source_qualified','is_current_pool','feature_available','trade_eligible','fit_eligible','is_required_held'):out[c]=out[c].eq(True)
    for c in ('security_id','security_id_type','cusip'):
        actual='security_uid' if c=='security_id' else c
        oldcol='original_'+c
        conflict=out[oldcol].map(_known)&out[actual].map(_known)&out[oldcol].ne(out[actual])
        out.loc[conflict,'identity_qualified']=False;out.loc[conflict,'block_reason']='ORIGINAL_B_SECURITY_DECLARATION_CONFLICT'
    absent=out.security_uid.isna();out.loc[absent,'identity_qualified']=False;out.loc[absent,'block_reason']='MISSING_EXACT_CURRENT_FEATURE_SECURITY_UID'
    out['train_structure_eligible']=out.fit_eligible&out.identity_qualified&out.source_qualified
    out['alpha_structure_eligible']=out.trade_eligible&out.identity_qualified&out.source_qualified
    out['eligible_for_policy']=False
    out=out.sort_values(KEYS,kind='stable').reset_index(drop=True)
    return out

def _counts(rows):
    result={}
    for name,mask in dict(full_train=rows.fit_eligible,full_held=rows.is_required_held,current_eligible=rows.trade_eligible,all_history=pd.Series(True,index=rows.index)).items():
        q=rows.loc[mask];good=q.identity_qualified&q.source_qualified
        result[name]=dict(rows=len(q),qualified=int(good.sum()),blocked=int((~good).sum()),reasons=q.loc[~good,'block_reason'].fillna('SOURCE_FEATURE_METADATA_UNQUALIFIED').value_counts().to_dict())
    return result

def prepare(run):
    run,source,pins,bindings=source_binding(run)
    with runtime.stage_writer(run,'qualification'):
        reader=metadata_reader(source);fold=old_training.FoldReader(pins,numeric=False)
        calendar=reader.read('calendar',['trade_date'],date_field='trade_date').trade_date
        features=reader.read('prediction_features',old.FEATURE_META,date_field='signal_date')
        intervals=reader.read('uid_intervals',list(metadata_owner.CLASS_META)+['report_quarter','quarter_universe_fingerprint'],date_field='effective_start')
        raw=fold.read('raw_keys',['trade_date','ticker','code'])
        panel=fold.metadata();held=fold.held_metadata()
        rows=qualify_rows(features,raw,intervals,panel,held,calendar)
        path=run/ROWS_REF;assert_safe_output_path(path,kind='backtest',paths=resolve(REPO));path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():raise Blocked('IMMUTABLE_IDENTITY_ROWS_ALREADY_EXIST')
        rows.to_parquet(path,index=False)
        counts=_counts(rows)
        annual={}
        for year in model.YEARS:
            selected=rows.loc[rows.signal_date.dt.year.eq(year)]
            annual[str(year)]=_counts(selected)
        summary=dict(schema='B_R6_SEQUENCE_IDENTITY_SUPPORT_V1',research_id=ID,status='SOURCE_ONLY_METADATA_COMPLETE',bindings=bindings,rows_ref=ref(path),counts=counts,annual=annual,
            identity_binding='EXACT_FROZEN_INTERVAL_COORDINATE_FOR_MECHANISM',historical_availability='UNKNOWN',strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
            source_code_pins=[ref(Path(m.__file__)) for m in (metadata_owner,old_training,old,model)],
            output_roles={ALPHA_ROLE:dict(eligible_for_policy=False,domain='ALL_SOURCE_QUALIFIED_STRUCTURAL_TRADE_ELIGIBLE_KEYS'),POLICY_ROLE:dict(eligible_for_policy=False,qualification_required='ALL_REQUIRED_ELIGIBLE_PLUS_HELD_EXACT_KEYS')},
            metadata_read_audit=reader.audit+fold.audit,feature_label_prediction_values_read=0,test2026_reads=0,R5_results_reads=0,new_fit=0,
            memory_upper=dict(full_annual_rows_upper=402740,lookback=60,raw_B32_float64_bytes=402740*60*32*8,transformed64_float64_bytes=402740*60*64*8),
            contiguous_epoch_updates='ALL_COMMON_CALENDAR_DAYS;BEFORE_ELIGIBILITY_FILTER;NO_CROSS_UID_CARRY',lookbacks=list(model.LOOKBACKS))
        old.write(run,META_REF,summary,immutable=True)
        return summary

class Source:
    """Guarded source values are unreachable until live R6 admission + freeze."""
    def __init__(self,run,freeze_sha):
        self.run=runtime.guard_numeric(run,freeze_sha);self.freeze_sha=freeze_sha
        _,self.source,self.pins,self.bindings=source_binding(self.run)
        self.fold=old_training.FoldReader(self.pins,numeric=True)
        frozen=old.read_json(self.run/runtime.FILENAME);support=frozen['opportunity_support_ref']
        if Path(support['source_ref']).resolve()!=self.run/META_REF:raise Blocked('WHOLE_FROZEN_OPPORTUNITY_SUPPORT_REQUIRED')
        old._pin(support['source_ref'],support['sha256'],'R6_FROZEN_OPPORTUNITY_SUPPORT')
        self.catalogue_ref=_frozen_catalogue_ref(self.run,frozen)
        summary=old.read_json(self.run/META_REF)
        if summary.get('research_id')!=ID or summary.get('feature_label_prediction_values_read')!=0:raise Blocked('EXACT_R6_SOURCE_ONLY_SUPPORT_REQUIRED')
        r=summary['rows_ref'];old._pin(r['path'],r['sha256'],'R6_UID_SIDECAR')
        self.rows_dataset=ds.dataset(r['path'],format='parquet')
        self.pred_dataset=ds.dataset(self.source['sources']['prediction_features']['path'],format='parquet')
        # Existing physical pin/footers remain authoritative before feature body.
        self.history_guard=metadata_reader(self.source)
        self.calendar=self.history_guard.read('calendar',['trade_date'],date_field='trade_date').trade_date
    def rows(self,*,start=None,stop='2026-01-01',fit=False,alpha=False,held=False):
        cutoff=pd.Timestamp(stop)
        if cutoff>model.BOUNDARY:raise Blocked('PRE2026_SOURCE_PROJECTION_REQUIRED')
        expr=ds.field('signal_date')<pa.scalar(cutoff.to_pydatetime(),type=self.rows_dataset.schema.field('signal_date').type)
        if start is not None:expr&=ds.field('signal_date')>=pd.Timestamp(start).to_pydatetime()
        if fit:
            expr&=ds.field('train_structure_eligible')==True
            for name in old_training.CLOCKS[1:]:expr&=ds.field(name)<cutoff.to_pydatetime()
        if alpha:expr&=ds.field('alpha_structure_eligible')==True
        if held:expr&=ds.field('is_required_held')==True
        return self.rows_dataset.to_table(filter=expr).to_pandas().sort_values(KEYS,kind='stable').reset_index(drop=True)
    def _exact_numeric(self,name,columns,keys,*,stop,mature_before=None):
        runtime.guard_numeric(self.run,self.freeze_sha)
        dataset=self.fold.datasets[name] if name!='history' else self.pred_dataset
        if keys.empty:return pd.DataFrame(columns=KEYS+list(columns))
        pieces=[]
        # Exact signal/ticker tuple predicate before body projection; no full
        # year numeric load followed by eligibility filtering.
        for day,group in keys.groupby('signal_date',sort=False):
            expr=(ds.field('signal_date')==pa.scalar(pd.Timestamp(day).to_pydatetime(),type=dataset.schema.field('signal_date').type))&ds.field('ticker').isin(group.ticker.tolist())
            expr&=ds.field('signal_date')<pd.Timestamp(stop).to_pydatetime()
            if mature_before is not None:
                for c in old_training.CLOCKS[1:]:expr&=ds.field(c)<pd.Timestamp(mature_before).to_pydatetime()
            pieces.append(dataset.to_table(columns=KEYS+list(columns),filter=expr).to_pandas())
        out=pd.concat(pieces,ignore_index=True)
        if out.duplicated(KEYS).any():raise Blocked('EXACT_NUMERIC_SOURCE_KEY_CONFLICT')
        return keys[KEYS].merge(out,on=KEYS,how='left',validate='one_to_one',sort=False)
    def truth(self,keys,cutoff):
        model.training_metadata(keys,cutoff)
        y=self._exact_numeric('label',['y_open5'],keys,stop=cutoff,mature_before=cutoff)
        if not np.isfinite(y.y_open5.to_numpy(float)).all():raise Blocked('FULL_ELIGIBLE_LABEL_SUPPORT_BLOCKED_NO_DROP')
        return y.y_open5.to_numpy(float)
    def context(self,keys,stop,columns=FEATURES):
        if not set(columns).issubset(FEATURES):raise Blocked('B32_CONTEXT_ONLY')
        frame=self._exact_numeric('panel',columns,keys,stop=stop)
        if not np.isfinite(frame[list(columns)].to_numpy(float)).all():raise Blocked('FULL_CONTEXT_SOURCE_SUPPORT_BLOCKED_NO_DROP')
        return frame
    def windows(self,keys,length,*,cache_id):
        # Exact past metadata window keys computed first; only then features read.
        cal=pd.DatetimeIndex(self.calendar);dates=set()
        for day in keys.signal_date.unique():
            i=cal.get_indexer([day])[0]
            if i<0:raise Blocked('NONCALENDAR_REQUESTED_SIGNAL')
            dates.update(cal[max(0,i-length+1):i+1])
        stop=pd.Timestamp(keys.signal_date.max())+pd.Timedelta(days=1)
        hist=self.rows(start=min(dates),stop=stop)
        hist=hist.loc[hist.signal_date.isin(dates)&hist.ticker.isin(keys.ticker)]
        legal=qualified_history_keys(hist,keys,cal,length)
        values=self._exact_numeric('history',FEATURES,legal,stop=stop)
        history=hist.merge(values,on=KEYS,how='left',validate='one_to_one',sort=False)
        root=resolve(REPO).cache_root/'V24'/'B_METHOD_SPACE_R6'/self.run.name/'opportunity'/cache_id.replace(':','_')
        assert_safe_output_path(root,kind='cache',paths=resolve(REPO));root.mkdir(parents=True,exist_ok=True)
        shape=(len(keys),length,len(FEATURES));identity=dict(source_inputs_sha256=SOURCE_SHA,target_binding_sha256=BINDING_SHA,keys_sha256=old_training.metadata_digest(keys[[*KEYS,'security_uid','asset_epoch']]),feature_order=list(FEATURES),lookback=length,shape=list(shape));marker=root/'window_manifest.json'
        if marker.exists():
            if old.read_json(marker)!=identity:raise Blocked('OWN_WINDOW_CACHE_IDENTITY_CHANGED')
            x=np.load(root/'window.npy',mmap_mode='r',allow_pickle=False);mask=np.load(root/'mask.npy',mmap_mode='r',allow_pickle=False)
            if x.shape!=shape or mask.shape!=shape or mask.dtype!=np.dtype(bool):raise Blocked('OWN_WINDOW_CACHE_SHAPE_CHANGED')
            good=mask[:,-1].all(axis=1);return model.Windows(keys,x,mask,good,tuple(None if v else 'NO_LEGAL_COMPLETE_CURRENT_FEATURE_ROW' for v in good))
        x=np.lib.format.open_memmap(root/'window.npy',mode='w+',dtype='float64',shape=shape)
        mask=np.lib.format.open_memmap(root/'mask.npy',mode='w+',dtype='bool',shape=shape)
        qualified=[];reasons=[]
        for begin in range(0,len(keys),2048):
            subset=keys.iloc[begin:begin+2048].copy()
            local=model.build_windows(history.loc[history.signal_date.le(subset.signal_date.max())],subset,cal,length)
            x[begin:begin+len(subset)]=local.values;mask[begin:begin+len(subset)]=local.observed
            qualified.extend(local.qualified.tolist());reasons.extend(local.block_reasons)
        x.flush();mask.flush();marker.write_text(json.dumps(identity,sort_keys=True),encoding='utf8')
        return model.Windows(keys,x,mask,np.asarray(qualified,bool),tuple(reasons))


def identity_view(run,*,day=None,start=None,stop=None):
    """Own immutable metadata sidecar; temporal/column predicates before body."""
    run=Path(run).resolve();source_binding(run)
    summary=old.read_json(run/META_REF);r=summary['rows_ref']
    if summary.get('research_id')!=ID or summary.get('feature_label_prediction_values_read')!=0:raise Blocked('R6_IDENTITY_METADATA_OWNER_REQUIRED')
    path=old._safe_source(r['path']);old._pin(path,r['sha256'],'R6_IDENTITY_METADATA')
    if path!=run/ROWS_REF:raise Blocked('R6_OWN_IDENTITY_ROWS_REQUIRED')
    dataset=ds.dataset(path,format='parquet');expr=ds.field('signal_date')<model.BOUNDARY.to_pydatetime()
    if day is not None:
        d=pd.Timestamp(day)
        model._dates(pd.Series([d]));expr&=ds.field('signal_date')==d.to_pydatetime()
    if start is not None:expr&=ds.field('signal_date')>=pd.Timestamp(start).to_pydatetime()
    if stop is not None:
        end=pd.Timestamp(stop)
        if end>model.BOUNDARY:raise Blocked('PRE2026_IDENTITY_VIEW_REQUIRED')
        expr&=ds.field('signal_date')<end.to_pydatetime()
    columns=[*KEYS,'security_uid','asset_epoch','segment_start','security_id_type','cusip','title_of_class','moomoo_transport_code','active_13f_quarter','quarter_universe_fingerprint','identity_qualified','source_qualified','is_current_pool','block_reason']
    return dataset.to_table(columns=columns,filter=expr).to_pandas()

def _frozen_catalogue_ref(run,frozen):
    r=frozen.get('opportunity_catalogue_ref')
    if not isinstance(r,dict) or Path(r.get('source_ref','')).resolve()!=Path(run)/'work/R6_OPPORTUNITY_CATALOGUE_REUSE.json':raise Blocked('WHOLE_FROZEN_OPPORTUNITY_CATALOGUE_REQUIRED')
    old._pin(r['source_ref'],r.get('sha256'),'R6_FROZEN_OPPORTUNITY_CATALOGUE')
    return r


def qualified_history_keys(history,requested,calendar,length):
    """Reject unknown/different observed UID epochs before B32 body reads."""
    if length not in model.LOOKBACKS:raise Blocked('FROZEN_HISTORY_LOOKBACK_REQUIRED')
    model._dates(history.signal_date);model._dates(requested.signal_date)
    if not requested.identity_qualified.eq(True).all() or not requested.source_qualified.eq(True).all() or not requested.security_uid.map(_known).all() or not requested.asset_epoch.map(_known).all():raise Blocked('QUALIFIED_REQUESTED_WINDOW_DOMAIN_REQUIRED')
    calendar=pd.DatetimeIndex(calendar);model._dates(pd.Series(calendar))
    groups={key:rows for key,rows in history.groupby(['ticker','security_uid','asset_epoch'],sort=False)}
    selected=[]
    for key,rows in requested.groupby(['ticker','security_uid','asset_epoch'],sort=False):
        positions=calendar.get_indexer(rows.signal_date)
        if (positions<0).any():raise Blocked('NONCALENDAR_REQUESTED_SIGNAL')
        available=set()
        for i in positions:available.update(calendar[max(0,i-length+1):i+1])
        group=groups.get(key)
        if group is None:continue
        legal=group.signal_date.isin(available)&group.identity_qualified.eq(True)&group.source_qualified.eq(True)&group.feature_available.eq(True)
        selected.append(group.loc[legal])
    return pd.concat(selected).sort_index().copy() if selected else history.iloc[:0].copy()


def _own_artifact(run,relative,obj):
    path=Path(run)/relative;assert_safe_output_path(path,kind='backtest',paths=resolve(REPO))
    if path.exists():raise Blocked('UNREGISTERED_EXISTING_ARTIFACT_NO_OVERWRITE')
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp')
    if temp.exists():raise Blocked('UNREGISTERED_EXISTING_TEMP_PRESERVED')
    joblib.dump(obj,temp,compress=3);temp.replace(path);return ref(path)

def _mmap_descriptor(array):
    if isinstance(array,np.memmap):return dict(path=str(array.filename),shape=list(array.shape),file_shape=list(np.load(array.filename,mmap_mode='r',allow_pickle=False).shape),dtype=str(array.dtype))
    return array

def _array(value,run=None):
    if isinstance(value,dict) and set(value)=={'path','shape','file_shape','dtype'}:
        path=Path(value['path']).resolve()
        if run is not None:
            root=resolve(REPO).cache_root/'V24'/'B_METHOD_SPACE_R6'/Path(run).name/'opportunity'
            if not path.is_relative_to(root):raise Blocked('OWN_R6_ARRAY_CACHE_REQUIRED')
        array=np.load(path,mmap_mode='r',allow_pickle=False)
        if list(array.shape)!=value['file_shape'] or str(array.dtype)!=value['dtype'] or np.prod(value['shape'])!=array.size:raise Blocked('TASK_CACHE_DESCRIPTOR_CHANGED')
        return array.reshape(value['shape'])
    return value

def _worker(pipe,operation,name,x,y,dates,quantile,dependencies,payload,observed):
    def started(event):
        pipe.send(('FIT_START',event))
        if pipe.recv() is not True:raise Blocked('R6_PARENT_REJECTED_FIT_ACK')
    try:
        runtime.guard_numeric(payload['run'],payload['freeze_sha'])
        if operation=='window_scaler':
            window=model.Windows(payload['keys'],_array(x,payload['run']),_array(observed,payload['run']),np.asarray(payload['qualified'],bool),tuple(payload['block_reasons']))
            result,meta=model.fit_window_scaler(window,dates,payload['metadata'],payload['cutoff'],on_fit_started=started)
        elif operation=='bayes_scaler':
            model.training_metadata(payload['metadata'],payload['cutoff'])
            result,meta=mechanism.fit_weighted_scaler(_array(x,payload['run']),dict(weights=dates),on_fit_started=lambda _:started(dict(kind='scaler',components=['B32_BAYES_SCALER'],learned_units=1,backend_calls=0)))
        elif operation=='model':
            result,meta=model.fit_model(name,_array(x,payload['run']),y,dates,payload['metadata'],payload['cutoff'],lookback=payload.get('lookback'),dependencies=dependencies,on_fit_started=started)
        else:raise Blocked('R6_WORKER_OPERATION_NOT_FROZEN')
        pipe.send(('RESULT',result,meta))
    except BaseException as exc:pipe.send(('ERROR',type(exc).__name__,str(exc)))
    finally:pipe.close()

def worker_fit(run,freeze_sha,ledger,node_id,operation,name,x,y,weights,metadata,cutoff,*,lookback=None,windows=None):
    """Reuse existing spawn/1800s/ACK body; only R6 debit callback changes."""
    runtime.guard_numeric(run,freeze_sha);started=[]
    previous=[e for e in ledger.status['physical_events'] if e['node_id'].startswith(node_id+':') and e['node_id'][len(node_id)+1:].isdigit()]
    if previous:
        if any(e['status']!='COMPLETE' for e in previous):raise Blocked('STARTED_FAILED_PHYSICAL_FIT_NO_SCIENTIFIC_RETRY')
        artifact=previous[0].get('details',{}).get('fit_artifact')
        if not artifact:raise Blocked('COMPLETED_FIT_WITHOUT_OWN_RESULT_REF')
        old._pin(artifact['path'],artifact['sha256'],'OWN_COMPLETED_FIT')
        return joblib.load(artifact['path']),dict(exact_reuse=True,fit_units=0)
    def reserve(log,auth,prior,model_id,year,event,tuple_sha):
        if not isinstance(event,dict) or event.get('learned_units')!=len(event.get('components',[])):raise Blocked('EXACT_R6_COMPONENT_EVENT_REQUIRED')
        key=node_id+':'+str(len(started));ledger.reserve(LEARNED,key,event['learned_units'],physical_kind=event['kind']);started.append(key)
    owner=mechanism._clone(fit_owner._fit_job,{'_component_start':reserve,'write_json_atomic':lambda *a,**k:None})
    payload=dict(run=str(run),freeze_sha=freeze_sha,metadata=metadata,cutoff=cutoff,lookback=lookback)
    if windows is not None:payload.update(keys=windows.keys,qualified=windows.qualified.tolist(),block_reasons=windows.block_reasons)
    receipt=dict(fit_units=0,receipt_path=str(Path(run)/'work/R6_FIT_ACK_REUSED.json'))
    try:
        result=owner(operation,name,_mmap_descriptor(x),y,weights,None,(str(TORCH),str(EXTRA)),payload,_mmap_descriptor(windows.observed) if windows is not None else None,
            log=None,auth=None,prior=None,year=pd.Timestamp(cutoff).year,tuple_sha=content_hash(dict(node=node_id,freeze_sha=freeze_sha)),receipt=receipt,worker_target=_worker)
        artifact=_own_artifact(run,'models/fit_nodes/'+content_hash(node_id)+'.joblib',result)
        for key in started:ledger.complete(key,backend_receipt=receipt.get('physical_fit_metadata',[]),component_ack_count=receipt['fit_units'],fit_artifact=artifact)
        return result,receipt
    except BaseException as exc:
        for key in started:ledger.fail(key,error_type=type(exc).__name__,error=str(exc),scientific_retry=0)
        raise

def _scaled(source,windows,scaler,cache_id):
    root=resolve(REPO).cache_root/'V24'/'B_METHOD_SPACE_R6'/source.run.name/'opportunity'/cache_id.replace(':','_')
    assert_safe_output_path(root,kind='cache',paths=resolve(REPO));root.mkdir(parents=True,exist_ok=True)
    path=root/'scaled.npy';shape=(len(windows.keys),windows.values.shape[1],64)
    identity=dict(keys_sha256=old_training.metadata_digest(windows.keys[[*KEYS,'security_uid','asset_epoch']]),shape=list(shape),scaler_mean=np.asarray(scaler.mean_).tolist(),scaler_scale=np.asarray(scaler.scale_).tolist(),source_inputs_sha256=SOURCE_SHA,transform='SCALED32_PLUS_EXPLICIT_MISSING32');marker=root/'scaled_manifest.json'
    if marker.exists():
        if old.read_json(marker)!=identity:raise Blocked('OWN_SCALED_CACHE_IDENTITY_CHANGED')
        result=np.load(path,mmap_mode='r',allow_pickle=False)
        if result.shape!=shape:raise Blocked('OWN_SCALED_CACHE_SHAPE_CHANGED')
        return result
    values=np.lib.format.open_memmap(path,mode='w+',dtype='float64',shape=shape)
    for begin in range(0,len(values),2048):
        part=model.Windows(windows.keys.iloc[begin:begin+2048],windows.values[begin:begin+2048],windows.observed[begin:begin+2048],windows.qualified[begin:begin+2048],windows.block_reasons[begin:begin+2048])
        values[begin:begin+len(part.keys)]=model.transform_windows(part,scaler,'TCN')
    values.flush();marker.write_text(json.dumps(identity,sort_keys=True),encoding='utf8');return values

def _predict(model_obj,X):
    parts=[]
    for start in range(0,len(X),2048):parts.append(model.predict(model_obj,X[start:start+2048]))
    output={}
    for key in ('mean','sigma','q10'):
        output[key]=None if not parts or any(p.get(key) is None for p in parts) else np.concatenate([np.asarray(p[key],float) for p in parts])
    return output

def _training(source,cutoff,start=None,*,sequence=False):
    keys=source.rows(start=start,stop=cutoff,fit=True)
    model.training_metadata(keys,cutoff)
    if sequence:
        keys,proof=model.sample_training_keys(keys)
        old.write(source.run,'work/sequence_sampling_'+pd.Timestamp(cutoff).strftime('%Y%m%d')+'.json',dict(research_id=ID,cutoff=cutoff,proof=proof,freeze_sha256=source.freeze_sha),immutable=True)
    return keys,source.truth(keys,cutoff),model.opportunity.date_weights(keys.signal_date)

def _publish(source,name,year,keys,output,train,selected_window,model_ref,*,role=ALPHA_ROLE):
    runtime.guard_numeric(source.run,source.freeze_sha)
    if keys.empty or not (keys.identity_qualified&keys.source_qualified).all():raise Blocked('WHOLE_OUTPUT_ROLE_IDENTITY_REQUIRED')
    if output.get('mean') is None or not np.isfinite(output['mean']).all() or len(output['mean'])!=len(keys):raise Blocked('FULL_OUTPUT_ROLE_FINITE_POINT_REQUIRED')
    out=keys[[*KEYS,'security_uid','asset_epoch','security_id_type','cusip','active_13f_quarter','quarter_universe_fingerprint']].copy()
    out['raw_mu']=output['mean']
    if output.get('sigma') is not None:out['raw_scale']=output['sigma']
    if output.get('q10') is not None:out['native_q10']=output['q10']
    path=source.run/'OOF'/role/f'{name}_{year}.parquet'
    assert_safe_output_path(path,kind='backtest',paths=resolve(REPO));path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise Blocked('IMMUTABLE_GENUINE_OOF_ALREADY_EXISTS')
    out.to_parquet(path,index=False)
    receipt=dict(schema='B_R6_GENUINE_OPPORTUNITY_OOF_V1',research_id=ID,status='COMPLETE',output_role=role,model=name,year=year,
        genuine_selected_recipe_OOF=True,producer_role=('GENUINE_ANNUAL_META_OOF' if name.startswith('FUSION_') else 'GENUINE_ANNUAL_MODEL_OOF'),target=model.TARGET,target_clipped=False,target_cash_complete=False,
        cutoff=f'{year}-01-01T00:00:00+00:00',source_label_mature_max=pd.Timestamp(train.label_mature_date.max()).tz_localize('UTC').isoformat(),selected_lookback=selected_window,
        source_inputs_sha256=SOURCE_SHA,target_binding_sha256=BINDING_SHA,qualified_oof_contract_sha256=source.freeze_sha,model_ref=model_ref,output_ref=ref(path),
        training_sample=train.attrs.get('sequence_training_sample'),train_rows=len(train),identity_keys_sha256=old_training.metadata_digest(keys[[*KEYS,'security_uid','asset_epoch']]),rows=len(out),eligible_for_policy=role==POLICY_ROLE,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,native_q10_qualified=output.get('q10') is not None,uncertainty='NATIVE_POSTERIOR_OR_TYPED_UNKNOWN_NOT_INFIT_RMS',test2026_reads=0,R5_results_reads=0)
    old.write(source.run,f'receipts/R6_{role}_{name}_{year}.json',receipt,immutable=True);return receipt

def run_opportunity(run,freeze_sha):
    runtime.guard_numeric(run,freeze_sha)
    with runtime.stage_writer(run,'opportunity'):
        source=Source(run,freeze_sha);ledger=runtime.R6Ledger(run,freeze_sha);failures=[];completed=[];selected={};scalers={}
        # Every independent fixed slot is visited once. One failed length blocks
        # only that model's annual selection, not the rest of the fixed queue.
        for year in model.YEARS:
            losses={name:{length:[] for length in model.LOOKBACKS} for name in model.MODELS}
            for fold in model.inner_folds(year):
                cut=fold['cutoff'];validation_end=fold['validation_end']
                try:
                    train,y,weights=_training(source,cut,sequence=True)
                    valid,vy,vw=_training(source,validation_end,start=fold['validation_start'])
                except Exception as exc:
                    failures.append(dict(cohort=fold['id'],dependency='SOURCE',error=type(exc).__name__+':'+str(exc)));continue
                for length in model.LOOKBACKS:
                    cohort=fold['id']+'_L'+str(length)
                    try:
                        tw=source.windows(train,length,cache_id=cohort+'_train');vwnd=source.windows(valid,length,cache_id=cohort+'_valid')
                        scaler,ack=worker_fit(run,freeze_sha,ledger,cohort+':SCALER','window_scaler','shared',tw.values,None,weights,train,cut,lookback=length,windows=tw)
                        tx=_scaled(source,tw,scaler,cohort+'_train');vx=_scaled(source,vwnd,scaler,cohort+'_valid')
                    except Exception as exc:
                        failures.append(dict(cohort=cohort,dependency='WINDOW_SCALER',error=type(exc).__name__+':'+str(exc)));continue
                    for name in model.MODELS:
                        node=cohort+':'+name
                        try:
                            completed_path=Path(run)/'inner'/f'{node.replace(chr(58),chr(95))}.json'
                            if completed_path.exists():
                                saved=old.read_json(completed_path)
                                if saved.get('freeze_sha256')!=freeze_sha or saved.get('status')!='COMPLETE':raise Blocked('INNER_COMPLETED_RECEIPT_CHANGED')
                                losses[name][length].append(saved['date_weighted_mse']);completed.append(node);continue
                            x=tx.reshape(len(tx),-1) if name in ('TemporalMLP','LagLinear') else tx
                            prediction_x=vx.reshape(len(vx),-1) if name in ('TemporalMLP','LagLinear') else vx
                            fitted,ack=worker_fit(run,freeze_sha,ledger,node,'model',name,x,y,weights,train,cut,lookback=length)
                            prediction=_predict(fitted,prediction_x)['mean']
                            loss=float(np.average((vy-prediction)**2,weights=vw))
                            if not np.isfinite(loss):raise Blocked('NONFINITE_INNER_MSE_NO_RETRY')
                            old.write(run,f'inner/{node.replace(chr(58),chr(95))}.json',dict(research_id=ID,freeze_sha256=freeze_sha,status='COMPLETE',node=node,date_weighted_mse=loss,lookback=length,seed=model.SEED,scientific_retry=0),immutable=True)
                            losses[name][length].append(loss);completed.append(node)
                            print(f'R6 opportunity {node} COMPLETE',flush=True)
                        except Exception as exc:failures.append(dict(cohort=cohort,model=name,error=type(exc).__name__+':'+str(exc)))
                    del tw,vwnd,tx,vx;gc.collect()
            cut=f'{year}-01-01';stop=f'{year+1}-01-01'
            try:train,y,weights=_training(source,cut,sequence=True);alpha=source.rows(start=cut,stop=stop,alpha=True)
            except Exception as exc:failures.append(dict(cohort=f'ANNUAL_{year}',dependency='SOURCE',error=str(exc)));continue
            for name in model.MODELS:
                node=f'ANNUAL_{year}:{name}'
                try:
                    length=model.select_window(losses[name]);selected[node]=length;cohort=f'ANNUAL_{year}_L{length}'
                    tw=source.windows(train,length,cache_id=cohort+'_train')
                    if cohort not in scalers:
                        scaler,ack=worker_fit(run,freeze_sha,ledger,cohort+':SCALER','window_scaler','shared',tw.values,None,weights,train,cut,lookback=length,windows=tw)
                        scalers[cohort]=scaler
                    scaler=scalers[cohort];tx=_scaled(source,tw,scaler,cohort+'_train')
                    x=tx.reshape(len(tx),-1) if name in ('TemporalMLP','LagLinear') else tx
                    fitted,ack=worker_fit(run,freeze_sha,ledger,node,'model',name,x,y,weights,train,cut,lookback=length)
                    mref=_own_artifact(run,f'models/opportunity/{name}_{year}.joblib',dict(model=fitted,scaler=scaler,selected_window=length))
                    aw=source.windows(alpha,length,cache_id=cohort+'_alpha');ax=_scaled(source,aw,scaler,cohort+'_alpha')
                    predict_x=ax.reshape(len(ax),-1) if name in ('TemporalMLP','LagLinear') else ax
                    receipt_path=Path(run)/f'receipts/R6_{ALPHA_ROLE}_{name}_{year}.json'
                    receipt=_publish(source,name,year,alpha,_predict(fitted,predict_x),train,length,mref)
                    completed.append(node)
                    held=source.rows(start=cut,stop=stop,held=True)
                    required=pd.concat([alpha,held],ignore_index=True).drop_duplicates(KEYS).sort_values(KEYS,kind='stable').reset_index(drop=True)
                    if not (required.identity_qualified&required.source_qualified).all():
                        old.write(run,f'receipts/R6_POLICY_BLOCK_{name}_{year}.json',dict(research_id=ID,status='BLOCKED_FULL_REQUIRED_HELD_IDENTITY',output_role=POLICY_ROLE,required_rows=len(required),blocked_rows=int((~(required.identity_qualified&required.source_qualified)).sum()),alpha_receipt=ref(Path(run)/f'receipts/R6_{ALPHA_ROLE}_{name}_{year}.json'),eligible_for_policy=False),immutable=True)
                    else:
                        hw=source.windows(required,length,cache_id=node+'_policy');hx=_scaled(source,hw,scaler,node+'_policy');px=hx.reshape(len(hx),-1) if name in ('TemporalMLP','LagLinear') else hx
                        _publish(source,name,year,required,_predict(fitted,px),train,length,mref,role=POLICY_ROLE)
                    print(f'R6 opportunity {node} COMPLETE_ALPHA',flush=True)
                except Exception as exc:failures.append(dict(cohort=f'ANNUAL_{year}',model=name,error=type(exc).__name__+':'+str(exc)))
            try:
                train,y,weights=_training(source,cut)
                node=f'ANNUAL_{year}:BayesianRidge';context=source.context(train,cut);x=context[FEATURES].to_numpy(float)
                scaler,ack=worker_fit(run,freeze_sha,ledger,node+':SCALER','bayes_scaler','BayesianRidge',x,None,weights,train,cut)
                fitted,ack=worker_fit(run,freeze_sha,ledger,node,'model','BayesianRidge',scaler.transform(x),y,weights,train,cut)
                mref=_own_artifact(run,f'models/opportunity/BayesianRidge_{year}.joblib',dict(model=fitted,scaler=scaler))
                current=source.context(alpha,stop)
                _publish(source,'BayesianRidge',year,alpha,_predict(fitted,scaler.transform(current[FEATURES].to_numpy(float))),train,None,mref)
                completed.append(node);print(f'R6 opportunity {node} COMPLETE_ALPHA',flush=True)
            except Exception as exc:
                failures.append(dict(cohort=f'ANNUAL_{year}',model='BayesianRidge',error=type(exc).__name__+':'+str(exc)));continue
            try:
                distribution={m:None for m in model.DISTRIBUTION_PACKET}
                b=read_native_oof(source,year,'BayesianRidge',alpha,with_scale=True);distribution['BayesianRidge']=dict(mean=b['BayesianRidge__mu'].to_numpy(float),sigma=b['BayesianRidge__scale'].to_numpy(float))
                proofs=[]
                for m in model.DISTRIBUTION_PACKET[1:]:
                    f=read_native_oof(source,year,m,alpha,r4=True,with_scale=True);distribution[m]=dict(mean=f[m+'__mu'].to_numpy(float),sigma=f[m+'__scale'].to_numpy(float));proofs.append(f[m+'__source_sha256'].iloc[0])
                mix=model.distribution_ensemble(distribution)
                _publish(source,'FixedDistributionMixture',year,alpha,mix,train,None,dict(BayesianRidge=mref,native_receipt_sha256=proofs,deterministic_fit_units=0,mixture_rule='FIXED_EQUAL_GAUSSIAN_CDF_Q10_64_BISECTIONS'))
                completed.append(f'ANNUAL_{year}:FixedDistributionMixture')
            except Exception as exc:failures.append(dict(cohort=f'ANNUAL_{year}',model='FixedDistributionMixture',error=type(exc).__name__+':'+str(exc)))
        completion=dict(research_id=ID,status='FIXED_QUEUE_TERMINAL',completed=completed,failures=failures,selected_windows=selected,scientific_retry=0,actual_counts=ledger.status['actual_counts'],OOF_roles=[ALPHA_ROLE,POLICY_ROLE],test2026_reads=0,R5_results_reads=0)
        old.write(run,'work/R6_OPPORTUNITY_STAGE_COMPLETION.json',completion,immutable=True)
        return completion


R4_RUN=Path('D:/us-tech-quant-backtests/V24/20261003T181407+0000_ddb7b537')
R4_PACKET=('ridge','hgb','xgb','lgb','extra')
REUSE_FIELDS={'schema','status','model','cohort','capacity','seeds','target','target_clipped','target_cash_complete','raw_native_only','source_binding_sha256','source_fit_cutoff','source_label_mature_max','producer_sha256','genuine_selected_recipe_OOF','artifact','rows','columns','whole_matrix_freeze_sha256','specification_sha256','support_sha256','feature_order','test2026_rows_read'}

def _oof_clocks(receipt,year,*,r4):
    cut=pd.Timestamp(receipt.get('source_fit_cutoff' if r4 else 'cutoff'))
    mature=pd.Timestamp(receipt.get('source_label_mature_max'))
    if pd.isna(cut) or pd.isna(mature):raise Blocked('UNKNOWN_GENUINE_PRODUCER_CLOCK')
    cut=cut.tz_localize('UTC') if cut.tzinfo is None else cut.tz_convert('UTC')
    mature=mature.tz_localize('UTC') if mature.tzinfo is None else mature.tz_convert('UTC')
    if cut!=pd.Timestamp(f'{year}-01-01',tz='UTC') or not mature<cut or cut>=pd.Timestamp('2026-01-01',tz='UTC'):
        raise Blocked('GENUINE_NATIVE_SOURCE_FIT_OR_MATURITY_CLOCK_INVALID')
    return cut,mature

def native_reuse_catalogue():
    # Fixed 32 metadata receipts, no model deserialize/OOF body/metric read.
    records=[]
    for member in (*R4_PACKET,*model.DISTRIBUTION_PACKET[1:]):
        for year in model.YEARS:
            path=R4_RUN/'receipts'/f'OPPORTUNITY_{member}_{year}.json'
            r=_metadata_projection(path,REUSE_FIELDS)
            qualified=(r.get('schema')=='B_R4_RAW_NATIVE_OPPORTUNITY_OOF_V1' and r.get('status')=='COMPLETE' and r.get('cohort')==f'ANNUAL_{year}' and r.get('model')==member and r.get('target')==model.TARGET and r.get('target_clipped') is False and r.get('raw_native_only') is True and r.get('source_binding_sha256')==BINDING_SHA and r.get('genuine_selected_recipe_OOF') is True and r.get('test2026_rows_read')==0 and r.get('feature_order')==list(FEATURES))
            try:_oof_clocks(r,year,r4=True)
            except Exception:qualified=False
            records.append(dict(year=year,member=member,receipt_ref=ref(path),metadata=r,status='EXACT_NATIVE_REUSE_CANDIDATE' if qualified else 'BLOCKED_SOURCE_OR_TUPLE',model_deserialized=False,OOF_values_read=0))
    return records

def _pinned_receipt(source,year,member,*,r4=False,role=ALPHA_ROLE):
    runtime.guard_numeric(source.run,source.freeze_sha)
    if year not in model.YEARS:raise Blocked('FROZEN_ANNUAL_OOF_ONLY')
    if r4:
        frozen=old.read_json(source.run/runtime.FILENAME);_frozen_catalogue_ref(source.run,frozen)
        catalogue=old.read_json(source.run/'work/R6_OPPORTUNITY_CATALOGUE_REUSE.json')
        entry=next((v for v in catalogue['native_reuse_receipts'] if v['year']==year and v['member']==member),None)
        if entry is None or entry['status']!='EXACT_NATIVE_REUSE_CANDIDATE':raise Blocked('PINNED_EXACT_R4_NATIVE_RECEIPT_REQUIRED')
        rref=entry['receipt_ref'];old._pin(rref['path'],rref['sha256'],'R4_NATIVE_METADATA_REUSE')
        r=_metadata_projection(rref['path'],REUSE_FIELDS)
        if r!=entry['metadata']:raise Blocked('FROZEN_R4_NATIVE_RECEIPT_CHANGED')
        _oof_clocks(r,year,r4=True)
        return r,rref,r['artifact'],'native_mu','native_sigma'
    path=source.run/'receipts'/f'R6_{role}_{member}_{year}.json'
    r=old.read_json(path)
    if r.get('research_id')!=ID or r.get('output_role')!=role or r.get('year')!=year or r.get('model')!=member or r.get('status')!='COMPLETE' or r.get('genuine_selected_recipe_OOF') is not True or r.get('qualified_oof_contract_sha256')!=source.freeze_sha or r.get('target')!=model.TARGET:raise Blocked('EXACT_OWN_GENUINE_OOF_RECEIPT_REQUIRED')
    _oof_clocks(r,year,r4=False)
    return r,ref(path),r['output_ref'],'raw_mu','raw_scale'

def _native_identity_audit_guard(source,year,member,artifact,rref):
    frozen=old.read_json(source.run/runtime.FILENAME)
    audit_ref=frozen.get('native_oof_identity_audit_ref');binding_ref=frozen.get('opportunity_reader_engineering_binding_ref')
    for r,filename,label in ((audit_ref,'R6_NATIVE_OOF_IDENTITY_METADATA_AUDIT.json','NATIVE_OOF_IDENTITY_AUDIT'),(binding_ref,'R6_OPPORTUNITY_NATIVE_READER_ENGINEERING_BINDING_R1.json','NATIVE_READER_ENGINEERING_BINDING')):
        if not isinstance(r,dict) or Path(r.get('source_ref','')).resolve()!=source.run/'work'/filename:raise Blocked('FROZEN_NATIVE_METADATA_SUPPLEMENT_REQUIRED:'+label)
        old._pin(r['source_ref'],r.get('sha256'),label)
    audit=old.read_json(audit_ref['source_ref']);binding=old.read_json(binding_ref['source_ref'])
    if audit.get('research_id')!=ID or audit.get('new_fit')!=0 or audit.get('reads',{}).get('numeric_values')!=0 or audit.get('reads',{}).get('projected_native_columns')!=['signal_date','ticker','security_id']:raise Blocked('REAL_ZERO_VALUE_NATIVE_IDENTITY_AUDIT_REQUIRED')
    if binding.get('research_id')!=ID or binding.get('science_unchanged') is not True or binding.get('new_real_fit')!=0 or binding.get('replaced_execution_code_ref',{}).get('sha256')!=old.sha(Path(__file__)):raise Blocked('EXACT_NATIVE_READER_ENGINEERING_CODE_REQUIRED')
    ar=binding.get('native_identity_audit_ref',{})
    if Path(ar.get('path','')).resolve()!=Path(audit_ref['source_ref']).resolve() or ar.get('sha256')!=audit_ref['sha256']:raise Blocked('ENGINEERING_BINDING_NATIVE_AUDIT_CHANGED')
    r=next((r for r in audit['records'] if r['year']==year and r['member']==member),None)
    if r is None or r.get('status')!='PASS_EXACT_CURRENT_ELIGIBLE_SOURCE_UID_METADATA' or r.get('blocked_rows')!=0 or r.get('artifact_ref')!=artifact or r.get('receipt_ref')!=rref:raise Blocked('EXACT_NATIVE_IDENTITY_AUDIT_RECORD_REQUIRED')
    return r


def _oof_predicates(dataset,keys):
    for day,group in keys.groupby('signal_date',sort=False):
        yield (ds.field('signal_date')==pa.scalar(pd.Timestamp(day).to_pydatetime(),type=dataset.schema.field('signal_date').type))&ds.field('ticker').isin(group.ticker.tolist())


def _oof_source_metadata(dataset,keys,identity_field):
    """Whole requested source UID gate before projecting prediction values."""
    required={'security_uid','asset_epoch','identity_qualified','source_qualified'}
    if not required.issubset(keys) or keys.duplicated(KEYS).any() or not (keys.security_uid.map(_known)&keys.asset_epoch.map(_known)&keys.identity_qualified.eq(True)&keys.source_qualified.eq(True)).all():raise Blocked('FULL_QUALIFIED_CURRENT_OOF_UID_EPOCH_REQUIRED')
    model._dates(keys.signal_date)
    columns=[*KEYS,identity_field]
    parts=[dataset.to_table(columns=columns,filter=p).to_pandas() for p in _oof_predicates(dataset,keys)]
    values=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=columns)
    if values.duplicated(KEYS).any():raise Blocked('AMBIGUOUS_GENUINE_NATIVE_METADATA_KEY')
    frame=keys.merge(values.rename(columns={identity_field:'source_uid'}),on=KEYS,how='left',validate='one_to_one',sort=False)
    if len(values)!=len(keys) or not (frame.source_uid.map(_known)&frame.source_uid.eq(frame.security_uid)).all():raise Blocked('PREBODY_OOF_CURRENT_SOURCE_UID_MISSING_OR_MISMATCH_NO_STITCH')
    return frame


def read_native_oof(source,year,member,keys,*,r4=False,role=ALPHA_ROLE,with_scale=False):
    """Actual native projection: exact key+year before values, no labels/outcome."""
    if keys.empty or not pd.to_datetime(keys.signal_date).dt.year.eq(year).all():raise Blocked('EXACT_ANNUAL_OOF_REQUEST_DOMAIN_REQUIRED')
    r,rref,artifact,mu,scale=_pinned_receipt(source,year,member,r4=r4,role=role)
    if r4:_native_identity_audit_guard(source,year,member,artifact,rref)
    path=old._safe_source(artifact['path']);old._pin(path,artifact['sha256'],'NATIVE_GENUINE_OOF')
    footer=pq.ParquetFile(path)
    for i in range(footer.metadata.num_row_groups):
        stat=footer.metadata.row_group(i).column(footer.schema.names.index('signal_date')).statistics
        if stat is None or not stat.has_min_max or pd.Timestamp(stat.max)>=model.BOUNDARY:raise Blocked('UNKNOWN_OR_MIXED_OOF_DATE_BODY')
    dataset=ds.dataset(path,format='parquet')
    _oof_source_metadata(dataset,keys,'security_id' if r4 else 'security_uid')
    fields=[*KEYS,('security_id' if r4 else 'security_uid'),mu]
    if with_scale:
        if scale not in dataset.schema.names:raise Blocked('NATIVE_SCALE_UNKNOWN_NO_INFITTED_SUBSTITUTE')
        fields.append(scale)
    parts=[]
    for day,group in keys.groupby('signal_date',sort=False):
        expr=(ds.field('signal_date')==pa.scalar(pd.Timestamp(day).to_pydatetime(),type=dataset.schema.field('signal_date').type))&ds.field('ticker').isin(group.ticker.tolist())
        parts.append(dataset.to_table(columns=fields,filter=expr).to_pandas())
    values=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=fields)
    if values.duplicated(KEYS).any():raise Blocked('AMBIGUOUS_GENUINE_NATIVE_KEY')
    values=values.rename(columns={('security_id' if r4 else 'security_uid'):'source_uid',mu:member+'__mu',scale:member+'__scale'})
    frame=keys.merge(values,on=KEYS,how='left',validate='one_to_one',sort=False)
    if not frame.source_uid.eq(frame.security_uid).all():raise Blocked('OOF_CURRENT_SOURCE_UID_MISMATCH_NO_STITCH')
    wanted=[member+'__mu']+([member+'__scale'] if with_scale else [])
    if not np.isfinite(frame[wanted].to_numpy(float)).all():raise Blocked('FULL_GENUINE_PACKET_VALUE_SUPPORT_NO_SHRINK')
    cut,mature=_oof_clocks(r,year,r4=r4)
    if not pd.to_datetime(keys.signal_date,utc=True).ge(cut).all():raise Blocked('OOF_SIGNAL_BEFORE_REAL_PRODUCER_FIT_CUTOFF')
    frame[member+'__source_cutoff']=pd.Timestamp(cut,tz='UTC') if pd.Timestamp(cut).tzinfo is None else pd.Timestamp(cut)
    frame[member+'__source_label_mature_max']=pd.Timestamp(mature,tz='UTC') if pd.Timestamp(mature).tzinfo is None else pd.Timestamp(mature)
    frame[member+'__source_sha256']=rref['sha256'];frame[member+'__producer_role']='GENUINE_ANNUAL_MODEL_OOF' if r4 else r['producer_role']
    frame.attrs['native_receipt_ref']=rref;frame.attrs['exact_source_clocks_validated']=True;frame.attrs['prebody_source_uid_metadata_qualified']=True
    return frame

def r4_equal_packet(source,year,keys):
    frames=[read_native_oof(source,year,m,keys,r4=True) for m in R4_PACKET]
    result=keys.copy();result['native_equal_mu']=np.mean([f[m+'__mu'].to_numpy(float) for m,f in zip(R4_PACKET,frames)],axis=0)
    for m,f in zip(R4_PACKET,frames):
        for suffix in ('source_cutoff','source_label_mature_max','source_sha256','producer_role'):result[m+'__'+suffix]=f[m+'__'+suffix].to_numpy()
    actual_cuts=[pd.Timestamp(f[m+'__source_cutoff'].iloc[0]) for m,f in zip(R4_PACKET,frames)]
    if len(set(actual_cuts))!=1:raise Blocked('FIVE_REAL_PRODUCER_CUTOFFS_MUST_MATCH')
    result['verified_source_fit_cutoff']=actual_cuts[0]
    result['verified_source_label_mature_max']=max(pd.Timestamp(f[m+'__source_label_mature_max'].iloc[0]) for m,f in zip(R4_PACKET,frames))
    result['genuine_chronological_oof']=True
    result['native_sigma']=np.nan;result.attrs.update(packet=list(R4_PACKET),point_semantics='FIXED_COMPLETE_EQUAL_NATIVE_R4_B5D',sigma='UNKNOWN_NOT_INFIT',source_receipt_sha256=[f[m+'__source_sha256'].iloc[0] for m,f in zip(R4_PACKET,frames)],source_receipt_refs=[f.attrs['native_receipt_ref'] for f in frames],exact_all_real_source_clocks_validated=True,verified_full_five_member_genuine_clocks=True,eligible_for_policy=False)
    return result

def earlier_history(source,cutoff,members=model.PACKET,*,context=()):
    cutoff=pd.Timestamp(cutoff);parts=[]
    for year in model.YEARS:
        if year>=cutoff.year:continue
        keys=source.rows(start=f'{year}-01-01',stop=f'{year+1}-01-01',alpha=True)
        legal=model.opportunity.training_mask(keys,cutoff)&keys.identity_qualified&keys.source_qualified
        keys=keys.loc[legal].copy();model.training_metadata(keys,cutoff)
        h=keys.copy();h['y_open5']=source.truth(keys,cutoff)
        for member in members:
            f=read_native_oof(source,year,member,keys)
            for c in f:
                if c.startswith(member+'__'):h[c]=f[c].to_numpy()
        if context:
            features=source.context(keys,f'{year+1}-01-01',columns=context)
            for c in context:h[c]=features[c].to_numpy()
        for c in ('signal_date','execution_date','label_end_date','label_mature_date'):h[c]=pd.to_datetime(h[c],utc=True)
        parts.append(h)
    if not parts:raise Blocked('NO_EARLIER_GENUINE_OOF_NOT_INFITTED')
    result=pd.concat(parts,ignore_index=True);result.attrs.update(source_inputs_sha256=SOURCE_SHA,target_binding_sha256=BINDING_SHA,qualified_oof_contract_sha256=source.freeze_sha,target_coordinate=model.TARGET)
    return result

class NativeLearn:
    """Same compact physical input identity, sole R6 ledger, immutable own state."""
    def __init__(self,source,ledger,year):self.source,self.ledger,self.year=source,ledger,year;self.records={}
    def __call__(self,kind,name,inputs,compute,parameters=None):
        from scripts.research.a2.ensemble.joint_fusion_execution_r4 import compact_inputs
        compact=compact_inputs(inputs);parameters=parameters or {}
        # Name already identifies phase/role; aliases cannot merge fitted models.
        key=content_hash(dict(year=self.year,kind=kind,name=name,inputs=compact,parameters=parameters,freeze_sha=self.source.freeze_sha))
        if key in self.records:return self.records[key]
        found=next((e for e in self.ledger.status['physical_events'] if e['node_id']==key),None)
        if found is not None:
            if found['status']!='COMPLETE':raise Blocked('FAILED_OR_STARTED_NODE_NO_SCIENTIFIC_RETRY')
            artifact=found.get('details',{}).get('artifact')
            if artifact is None:raise Blocked('COMPLETE_NATIVE_STATE_ARTIFACT_REQUIRED')
            old._pin(artifact['path'],artifact['sha256'],'OWN_COMPLETED_NATIVE_STATE');value=joblib.load(artifact['path']);self.records[key]=value;return value
        method=parameters.get('method');units=2 if kind=='model_fit' and method in ('mlp_stack','mlp_gate') else 1
        self.ledger.reserve(LEARNED,key,units,physical_kind=kind)
        try:
            value=compute()
            if compact_inputs(inputs)!=compact:raise Blocked('NATIVE_PHYSICAL_INPUT_MUTATION')
            artifact=_own_artifact(self.source.run,f'models/fusion_states/{key}.joblib',value)
            self.ledger.complete(key,artifact=artifact,parameter_components=units,backend_calls=1 if kind=='model_fit' else 0)
            self.records[key]=value;return value
        except BaseException as exc:self.ledger.fail(key,error_type=type(exc).__name__,error=str(exc),scientific_retry=0);raise

def _uncertainty_year(source,ledger,year,learn,blocked):
    run=source.run;cut=f'{year}-01-01'
    for member in (*model.MODELS,'BayesianRidge','FixedDistributionMixture'):
        try:
            h=earlier_history(source,cut,(member,))
            if member in ('BayesianRidge','FixedDistributionMixture'):
                for sy in sorted(pd.to_datetime(h.signal_date).dt.year.unique()):
                    mask=pd.to_datetime(h.signal_date).dt.year.eq(sy);keys=source.rows(start=f'{sy}-01-01',stop=f'{sy+1}-01-01',alpha=True)
                    values_scale=read_native_oof(source,sy,member,keys,with_scale=True)[KEYS+[member+'__scale']]
                    naive=h.loc[mask,KEYS].copy();naive.signal_date=pd.to_datetime(naive.signal_date).dt.tz_localize(None)
                    h.loc[mask,member+'__scale']=naive.merge(values_scale,on=KEYS,how='left',validate='one_to_one')[member+'__scale'].to_numpy()
            result=model.fit_native_uncertainty(h,pd.Timestamp(cut,tz='UTC'),member,learn)
            old.write(run,f'receipts/R6_NATIVE_UNCERTAINTY_{member}_{year}.json',dict(research_id=ID,year=year,model=member,result={k:v for k,v in result.items() if k not in ('model','scaler')},source_cutoff=cut,native_mean_transform='IDENTITY',eligible_for_policy=False),immutable=True)
        except Exception as exc:blocked.append(dict(year=year,uncertainty=member,error=type(exc).__name__+':'+str(exc)))

def _residual_year(source,ledger,year,learn,blocked,completed):
    run=source.run;cut=f'{year}-01-01';stop=f'{year+1}-01-01'
    current=source.rows(start=cut,stop=stop,alpha=True)
    values={}
    try:values['TCN']=read_native_oof(source,year,'TCN',current)
    except Exception as exc:blocked.append(dict(year=year,method=model.FUSIONS[-1],error=type(exc).__name__+':'+str(exc)));return
    # Native residual producer remains a separate explicit branch.
    try:
        residual_history=earlier_history(source,cut,('TCN',),context=FEATURES)
        node=f'R6_RESIDUAL_{year}'
        starts=[]
        def started(event):ledger.reserve(LEARNED,node,event['learned_units'],physical_kind=event['kind']);starts.append(node);return True
        fit=model.fit_residual(residual_history,pd.Timestamp(cut,tz='UTC'),on_fit_started=started)
        for key in starts:ledger.complete(key,backend_calls=2,components=['B32_SCALER','RIDGE_RESIDUAL'])
        mref=_own_artifact(run,f'models/meta/residual_tcn_then_ridge_{year}.joblib',fit)
        x=source.context(current,stop)[FEATURES].to_numpy(float)
        mu=values['TCN']['TCN__mu'].to_numpy(float)+fit['secondary'].predict(fit['scaler'].transform(x))
        sigma=None
        if year>2023:
            composite=earlier_history(source,cut,('FUSION_residual_tcn_then_ridge',))
            prepare=lambda h,c,m:model.fusion.prepare_history(h,c,m,producer_role='GENUINE_ANNUAL_META_OOF')
            rms_fn=mechanism._clone(model.fusion.fit_meta,{'prepare_history':prepare})
            rms_result=rms_fn(composite,pd.Timestamp(cut,tz='UTC'),'equal',('FUSION_residual_tcn_then_ridge',),learn,seeds=(model.SEED,),fixed_weights=(1.,))
            if rms_result.get('qualified'):sigma=np.full(len(current),rms_result['prior_OOF_error_RMS'])
        _publish(source,'FUSION_residual_tcn_then_ridge',year,current,dict(mean=mu,sigma=sigma,q10=None),residual_history.assign(label_mature_date=pd.to_datetime(residual_history.label_mature_date).dt.tz_localize(None)),None,mref)
        completed.append(dict(year=year,method=model.FUSIONS[-1]))
    except Exception as exc:
        for key in locals().get('starts',[]):
            event=next(e for e in ledger.status['physical_events'] if e['node_id']==key)
            if event['status']=='STARTED':ledger.fail(key,error_type=type(exc).__name__,error=str(exc))
        blocked.append(dict(year=year,method=model.FUSIONS[-1],error=type(exc).__name__+':'+str(exc)))

def run_fusion(run,freeze_sha):
    runtime.guard_numeric(run,freeze_sha)
    with runtime.stage_writer(run,'fusion'):
        source=Source(run,freeze_sha);ledger=runtime.R6Ledger(run,freeze_sha);completed=[];blocked=[]
        # Bind only the already-present native Torch snapshot; no installation.
        model.sequence._torch((str(TORCH),))
        for year in (2023,2024,2025):
            cut=f'{year}-01-01';stop=f'{year+1}-01-01';learn=NativeLearn(source,ledger,year)
            _uncertainty_year(source,ledger,year,learn,blocked)
            _residual_year(source,ledger,year,learn,blocked,completed)
            try:
                history=earlier_history(source,cut,context=model.fusion.CONTEXT)
                current=source.rows(start=cut,stop=stop,alpha=True);values={}
                for member in model.PACKET:values[member]=read_native_oof(source,year,member,current)
                context=source.context(current,stop,columns=model.fusion.CONTEXT)
                expert=np.column_stack([values[m][m+'__mu'].to_numpy(float) for m in model.PACKET])
            except Exception as exc:blocked.append(dict(year=year,dependency='COMPLETE_EARLIER_CURRENT_PACKET',error=type(exc).__name__+':'+str(exc)));continue
            for method in model.FUSIONS[:-1]:
                try:
                    fit=model.fit_fusion(history,pd.Timestamp(cut,tz='UTC'),method,learn)
                    if fit.get('qualified') is not True:raise Blocked('SCIENTIFIC_META_FIT_FAILED_NO_RETRY:'+str(fit.get('errors')))
                    mu=fit['model'].predict(expert,context[list(model.fusion.CONTEXT)].to_numpy(float))
                    mref=_own_artifact(run,f'models/meta/{method}_{year}.joblib',fit)
                    _publish(source,'FUSION_'+method,year,current,dict(mean=mu,sigma=np.full(len(current),fit['prior_OOF_error_RMS'])),history.assign(label_mature_date=pd.to_datetime(history.label_mature_date).dt.tz_localize(None)),None,mref)
                    completed.append(dict(year=year,method=method));print(f'R6 fusion {year} {method} COMPLETE_ALPHA',flush=True)
                except Exception as exc:blocked.append(dict(year=year,method=method,error=type(exc).__name__+':'+str(exc)))
        completion=dict(research_id=ID,status='FIXED_FUSION_QUEUE_TERMINAL',completed=completed,blocked=blocked,scientific_retry=0,actual_counts=ledger.status['actual_counts'],test2026_reads=0,R5_results_reads=0)
        old.write(run,'work/R6_FUSION_STAGE_COMPLETION.json',completion,immutable=True);return completion

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--phase',choices=('prepare','opportunity','fusion','all'),required=True);parser.add_argument('--freeze-sha')
    args=parser.parse_args()
    if args.phase=='prepare':result=prepare(args.run);print(json.dumps(dict(status=result['status'],counts=result['counts']),ensure_ascii=False));return
    if not args.freeze_sha:raise Blocked('WHOLE_FREEZE_SHA_REQUIRED_BEFORE_NUMERIC')
    if args.phase in ('opportunity','all'):run_opportunity(args.run,args.freeze_sha)
    if args.phase in ('fusion','all'):run_fusion(args.run,args.freeze_sha)

if __name__=='__main__':main()
