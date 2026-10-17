"""C14 metadata-only B R5 consumer contract; no estimator or price reader.

The original R5 EventWitness/structural_identity owns event semantics. C14 is a
new descendant admission, never an exact C13 repair or a strict-PIT upgrade.
Numeric matrices are not deserialized by this readiness module.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json
import pandas as pd
from scripts.research.a2.risk.event_risk_contract_r5 import EventWitness,structural_identity
from scripts.common.storage_paths import assert_safe_output_path

ID='V24_C_SELECTOR_MAXIMAL_BREADTH_PRE2026_C14'
B_RUN=Path('D:/us-tech-quant-backtests/V24/20261004T044305+0000_d21499cc')
FILES={'bank':'models/risk/EVENT_RISK_BANK_R5.json','freeze':'R5_SCIENCE_AND_EXECUTION_FREEZE.json','qualification':'support/RISK_EVENT_QUALIFICATION_R5.json'}
FAMILIES=('DIAG','SAMPLE','LW','OAS','CONSTANT_CORRELATION','EWMA','PCA_FACTOR','QQQ_RESIDUAL','FF48_HIERARCHICAL','DOWNSIDE_SEMIVARIANCE','TAIL_CVAR','REGIME_COVARIANCE','UNCERTAINTY_JACKKNIFE','DISAGREEMENT_ENSEMBLE','SHR_HP','SHR_EB')
NO_NATIVE=('DIAG','SAMPLE','GARCH','GJR_GARCH')
HYBRIDS=(('RIDGE','DIAG'),('HGB','LW'),('XGB','QQQ_RESIDUAL'),('CAT','DOWNSIDE_SEMIVARIANCE'),('MLP','REGIME_COVARIANCE'),('QUANTILE','UNCERTAINTY_JACKKNIFE'))
CLASSICAL=(('D01','LW','D02'),('D02','LW','RAW_IDENTITY'),('D03','DOWNSIDE_SEMIVARIANCE','D03'),('D04','TAIL_CVAR','D04'),('D05','OAS','D05'),('D06','EWMA','D06'),('D07','DOWNSIDE_SEMIVARIANCE','D07'),('D08','UNCERTAINTY_JACKKNIFE','D08'),('D09','SHR_HP','D09'),('D10','PCA_FACTOR','D10'),('D11','QQQ_RESIDUAL','D11'),('D12','DISAGREEMENT_ENSEMBLE','STABILITY_500'))

def specification():
    return {'research_id':ID,'identity':'C14_EVENT_DRIVEN_RISK_DESCENDANT','owner_run':str(B_RUN),'files':FILES,'families':list(FAMILIES),'permanent_blocked_methods':list(NO_NATIVE),'hybrid_bindings':[{'candidate_id':'C14_RX_'+h+'_'+f,'head':h,'family':f} for h,f in HYBRIDS],'classical_bindings':[{'candidate_id':'C14_'+d,'family':f,'existing_rule':m} for d,f,m in CLASSICAL],'cadence':'structural ordered U/UID/epoch/source change; otherwise exact carry','horizon_sessions':5,'strict_PIT_promotion_eligible':False,'history_policy':'NO_CROSS_IDENTITY_STITCHING; independently qualified current UID epoch; native N0 HP premise disclosed','numeric_admission':'formal B freeze + bank + full-U exact source/cutoff/ordered UID/epoch/horizon/params; no family padding','uncertainty_admission':'full PSD covariance replicas required for robust rule; scalar sigma is not covariance ensemble','tail_admission':'independently qualified explicit scenario matrix required; covariance is not CVaR','gates':'fixed C14_P01 G0 final set; whole-set checks only; fail veto entire proposed set, no rematch/rerank; missing source typed BLOCKED, never Raw success','new_risk_estimation_by_C':0,'learned_cap_attributable_to_C14':3000,'bootstrap_stability':{'draws':500,'block':20,'seed':20260928,'status':'BLOCKED_BUDGET_NO_SEPARATE_AUTHORIZED_RESERVATION'},'RX7':'BLOCKED_BUDGET_WHOLE_DIAGNOSTIC_ARM_PREOUTCOME'}

def readiness(root=B_RUN):
    root=Path(root);assert_safe_output_path(root,kind='backtest')
    if root.resolve()!=B_RUN.resolve():raise ValueError('EXACT_FROZEN_B_R5_OWNER_REQUIRED')
    checks={k:(root/v).is_file() for k,v in FILES.items()}
    return {'status':'PUBLISHED_METADATA_REVIEW_REQUIRED' if all(checks.values()) else 'WAITING_B_R5_NUMERIC_BANK','files':checks,'numeric_reads':0,'new_fits':0,'new_solves':0,'strict_PIT_promotion_eligible':False}

def qualify_header(record,current,decision_asof,recipe_sha256):
    """Pure header admission. Caller separately pins artifact bytes before use."""
    at=pd.Timestamp(decision_asof)
    if at.tzinfo is None or at>=pd.Timestamp('2026-01-01',tz='UTC'):raise ValueError('PRE2026_EXPLICIT_CLOCK_REQUIRED')
    if record.get('status')!='PASS_FROZEN_HISTORY_MECHANISM' or record.get('strict_PIT_promotion_eligible') is not False:raise ValueError('NO_STRICT_PIT_OR_BLOCKED_STATE_ADMISSION')
    family=record.get('family')
    if family not in FAMILIES or family in NO_NATIVE:raise ValueError('UNSUPPORTED_FROZEN_FAMILY')
    assets=tuple(current['assets'])
    signature=structural_identity(assets=assets,uids=current['asset_uids'],epochs=current['asset_epochs'],security_coordinate=current['security_coordinate'],source_support_identity=current['source_support_identity'])
    if record.get('recipe_sha256')!=recipe_sha256 or record.get('horizon_sessions')!=5:raise ValueError('EXACT_RECIPE_AND_NATIVE_H5_REQUIRED')
    for k in ('assets','asset_uids','asset_epochs'):
        if record.get(k)!=current[k]:raise ValueError('NO_FULL_U_UID_EPOCH_PADDING')
    asof=pd.Timestamp(record['as_of']);cutoff=pd.Timestamp(record['cutoff'])
    if asof.tzinfo is None or cutoff.tzinfo is None or not cutoff<asof<=at:raise ValueError('STRICT_HISTORY_STATE_CUTOFF_REQUIRED')
    EventWitness(str(at),signature,record['structural_identity'],record.get('source_still_valid') is True,record.get('maturity_still_valid') is True).validate(asof)
    ref=record.get('artifact_ref',{})
    p=Path(ref.get('path',''));digest=ref.get('sha256','')
    if not p.is_absolute() or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('PINNED_ARTIFACT_REFERENCE_REQUIRED')
    assert_safe_output_path(p,kind='backtest')
    return {'status':'HEADER_QUALIFIED_ONLY','family':family,'artifact_ref':ref,'numeric_read_authority':False,'strict_PIT_promotion_eligible':False}