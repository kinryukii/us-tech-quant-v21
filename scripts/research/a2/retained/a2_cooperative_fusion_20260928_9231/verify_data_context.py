"""Independent bounded checks for the new read-only OOF context interface."""
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import data_context as d


def main():
    checks={};stages={};all_sources={}
    for stage,(years,cutoff) in d.STAGES.items():
        before=d.training_sources(stage)
        frame=d.load_training(stage)
        original=pd.concat([pd.read_parquet(d.BASE_ROOT/f'ensemble_artifacts/oof_{y}.parquet') for y in years],ignore_index=True)
        for c in ['signal_date','label_end_date','base_fit_cutoff']:original[c]=pd.to_datetime(original[c])
        preserved=frame[original.columns].copy();preserved.attrs={};original.attrs={}
        pd.testing.assert_frame_equal(preserved,original,check_exact=True)
        x=d.meta_features(frame);g=d.gate_features(frame)
        gate=pd.DataFrame(g,columns=d.GATE_COLUMNS)
        for c in ['signal_date','ticker','state_id']:gate[c]=frame[c].to_numpy()
        shared=gate.groupby(['signal_date','ticker','state_id'])[d.GATE_COLUMNS].nunique().eq(1).all().all()
        checks[stage+'_original_oof_exact_including_row_order']=True
        checks[stage+'_same_state_gate_action_independent']=bool(shared)
        checks[stage+'_meta_six_ranks_exact']=bool(np.array_equal(x[:,:6],frame[d.RANK_COLUMNS].to_numpy(float)))
        checks[stage+'_source_clock_strict']=bool(frame.signal_date.lt(cutoff).all() and frame.label_end_date.lt(cutoff).all())
        checks[stage+'_bounded_signed_ranks']=bool(frame[d.RANK_COLUMNS].abs().le(1).all().all())
        checks[stage+'_source_bytes_unchanged']=before==d.training_sources(stage)
        # Two bounded frozen-baseline predict calls exercise the promised interface.
        p=d.linear_baseline_predict(frame.iloc[:15],stage)
        model=d.load_linear_baseline(stage)
        expected=frame.iloc[:15][d.RANK_COLUMNS].to_numpy(float)@model.coef_+model.intercept_
        checks[stage+'_old_baseline_exact_six_input_predict']=bool(np.allclose(p,expected,rtol=0,atol=1e-18))
        stages[stage]={'rows':len(frame),'days':int(frame.signal_date.nunique()),
            'gate_state_groups':len(gate[['signal_date','ticker','state_id']].drop_duplicates()),
            'input_shape':list(x.shape),'gate_shape':list(g.shape),'label_end_max':str(frame.label_end_date.max().date())}
        all_sources.update(before)
    checks['all_source_files_unchanged_after_checks']=all(d.sha(p)==h for p,h in all_sources.items())
    receipt={'status':'PASS' if all(checks.values()) else 'FAIL','created_utc':datetime.now(timezone.utc).isoformat(),
        'checks':checks,'stages':stages,'old_source_hashes_checked':len(all_sources),
        'new_fit_calls':0,'base_fit_calls':0,'frozen_linear_predict_calls':2,'prediction_rows_per_call':15,
        'test2026_rows_read':0,'no_2026_prediction_or_result_file_opened':True,
        'meaning':'Data/clock/interface verification only; not a performance or historical source-PIT certification.'}
    (d.ROOT/'DATA_CONTEXT_VERIFY.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
    assert all(checks.values()),checks
    print(json.dumps(receipt,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
