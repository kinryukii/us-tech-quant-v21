"""Verify saved RL time and accounting boundaries without re-fitting."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import pandas as pd

here=Path(__file__).resolve().parent
report=json.loads((here/'POLICY_GRADIENT_REPORT.json').read_text(encoding='utf-8'))
preflight=json.loads((here/'RL_TIME_LEAKAGE_PREFLIGHT.json').read_text(encoding='utf-8'))
assert preflight['status']=='PASS_PRETRAIN_TIMING_BOUND'
assert report['2026_input_used_for_fit_selection_or_reward'] is False
assert report['total_policy_optimizer_steps_including_aborted_pilot']==33
assert report['total_preprocessor_fit_calls_including_aborted_pilot']==3
for log in report['train_log']+report['full_pre2026_train_log']:
    year=log['episode_year']
    assert pd.Timestamp(log['last_signal']).year==year
    assert pd.Timestamp(log['terminal_price_date']).year==year
    assert pd.Timestamp(log['terminal_price_date'])<pd.Timestamp('2026-01-01')
assert len(report['train_log'])==8 and len(report['full_pre2026_train_log'])==24
ledgers=[]
identity_columns=None
for year,name in [(2024,'validation_2024_daily_ledger.parquet'),(2025,'final_2025_daily_ledger.parquet')]:
    path=here/name
    frame=pd.read_parquet(path)
    dates=pd.to_datetime(frame.execution_date)
    assert dates.min().year==year and dates.max().year==year
    assert dates.max()<pd.Timestamp('2026-01-01')
    assert frame.reconstructed_transaction_cost.ge(0).all()
    assert frame.reconstructed_nav.gt(0).all()
    cols=[c for c in frame if c.endswith('_IDENTITY_ERROR')]
    assert len(cols)==5 and (frame[cols].abs().max()<1e-8).all()
    identity_columns=cols
    ledgers.append({'year':year,'rows':len(frame),'min_consumed_price_date':str(dates.min().date()),
                    'max_consumed_price_date':str(dates.max().date()),
                    'max_abs_accounting_identity_error':float(frame[cols].abs().max().max()),
                    'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
result={'status':'PASS_POSTFIT_TIMING_AND_ACCOUNTING','cutoff_exclusive':'2026-01-01',
        'annual_episode_train_steps':{'2023':16,'2024':8,'2025':8},
        'optimizer_steps_including_aborted_2020_22_pilot':33,
        'scaler_fits_including_aborted_2020_22_pilot':3,
        'full_pre2026_refit_train_log_max_consumed_price_date':max(x['terminal_price_date'] for x in report['full_pre2026_train_log']),
        'no_2026_fit_reward_selection_or_eval':True,'identity_columns':identity_columns,'ledgers':ledgers,
        'scope_note':'Checks saved report/log and ledger bounds; original QFQ vendor history was not independently reconstructed.'}
(here/'POSTFIT_LEAKAGE_AND_ACCOUNTING_AUDIT.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
