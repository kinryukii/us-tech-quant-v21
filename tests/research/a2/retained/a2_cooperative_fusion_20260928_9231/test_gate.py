"""Focused gate contract tests on synthetic states; no production refits."""
import json
import numpy as np
import pandas as pd
import pytest
import torch

import gate


def frame(year=2024):
    rows=[]
    for state in range(2):
        for action in [0.,.025,.05,.075,.1]:
            r=dict(signal_date=pd.Timestamp(f'{year}-03-01'),label_end_date=pd.Timestamp(f'{year}-03-05'),
                base_fit_cutoff=pd.Timestamp(f'{year}-01-01'),ticker='A',state_id=state,action=action,
                current_weight=.05*state,cash_weight=.95-.45*state,age=10*state,
                realized_vol_20d=.02+.005*state,ret_20d=.03-.01*state,target_advantage=.001*action)
            for index,name in enumerate(gate.RANK_COLUMNS):r[name]=(index+1)*action
            rows.append(r)
    return pd.DataFrame(rows)


def checkpoint(directory,stage='validation'):
    torch.manual_seed(gate.SEED)
    model=gate.ConditionalGate()
    model_path=directory/f'{stage}_gate.pt';torch.save(model.state_dict(),model_path)
    norm=directory/f'{stage}_normalization.npz'
    np.savez(norm,mean=np.zeros(5),scale=np.ones(5),target_scale=np.array(.003))
    receipt={'status':'PASS','stage':stage,'label_end_max':'2024-12-31' if stage=='validation' else '2025-12-31',
        'model_sha256':gate.sha(model_path),'normalization_sha256':gate.sha(norm)}
    (directory/f'{stage}_RECEIPT.json').write_text(json.dumps(receipt),encoding='utf-8')
    return model


def test_frozen_parameter_count_and_simplex_and_zero_baseline():
    torch.manual_seed(12);model=gate.ConditionalGate()
    assert sum(p.numel() for p in model.parameters())==103
    features=torch.randn(100,5)
    score,weights=model(features,torch.zeros(100,6))
    assert torch.all(weights>0) and torch.isfinite(weights).all()
    assert torch.allclose(weights.sum(dim=1),torch.ones(100),atol=2e-7)
    assert torch.equal(score,torch.zeros(100))
    assert float(model.calibration())>0


def test_checkpoint_load_predict_contributions_and_frozen_parameters(tmp_path):
    checkpoint(tmp_path)
    loaded=gate.GateModel('validation',artifact_dir=tmp_path)
    original={key:value.clone() for key,value in loaded.network.state_dict().items()}
    sample=frame()
    scores,weights=loaded.predict(sample)
    contributions=sample[gate.RANK_COLUMNS].to_numpy()*weights*loaded.output_scale
    np.testing.assert_allclose(scores,contributions.sum(axis=1),rtol=1e-14,atol=1e-18)
    assert loaded.output_scale>0
    assert all(torch.equal(value,original[key]) for key,value in loaded.network.state_dict().items())
    assert scores[sample.action.eq(0)].tolist()==[0.,0.]
    second=gate.GateModel('validation',artifact_dir=tmp_path)
    np.testing.assert_array_equal(weights,second.predict(sample)[1])


def test_action_expert_scores_and_future_labels_cannot_change_weights(tmp_path):
    checkpoint(tmp_path);model=gate.GateModel('validation',artifact_dir=tmp_path)
    sample=frame();weights=model.predict(sample)[1]
    for state in sample.state_id.unique():
        w=weights[sample.state_id.eq(state)]
        np.testing.assert_allclose(w,np.repeat(w[:1],5,axis=0),atol=0,rtol=0)
    changed=sample.copy()
    changed['action']=100.;changed['target_advantage']=-1e8;changed['label_end_date']=pd.Timestamp('2099-01-01')
    changed[gate.RANK_COLUMNS]=-10.
    np.testing.assert_array_equal(weights,model.predict(changed)[1])


@pytest.mark.parametrize('stage,year',[('validation',2025),('final',2026)])
def test_training_rejects_future_year(stage,year):
    with pytest.raises(ValueError,match='TIME_LEAKAGE'):
        gate.validate_training_frame(frame(year),stage)


def test_training_rejects_unmatured_labels_and_wrong_base_year():
    sample=frame();gate.validate_training_frame(sample,'validation')
    with pytest.raises(ValueError,match='TIME_LEAKAGE'):
        gate.validate_training_frame(sample.assign(label_end_date=pd.Timestamp('2025-01-02')),'validation')
    with pytest.raises(ValueError,match='BASE_STAGE_MISMATCH'):
        gate.validate_training_frame(sample.assign(base_fit_cutoff=pd.Timestamp('2023-01-01')),'validation')
    with pytest.raises(ValueError,match='INCOMPLETE_FIVE_ACTION'):
        gate.validate_training_frame(sample.iloc[:-1],'validation')


def test_sample_order_uses_keys_only():
    original=frame();changed=original.copy()
    changed[gate.RANK_COLUMNS]=-1e10;changed['target_advantage']=1e10
    np.testing.assert_array_equal(gate.deterministic_order(original),gate.deterministic_order(changed))


def test_checkpoint_tampering_and_stage_errors_are_rejected(tmp_path):
    checkpoint(tmp_path)
    with (tmp_path/'validation_gate.pt').open('ab') as handle:handle.write(b'tamper')
    with pytest.raises(ValueError,match='HASH_STAGE_OR_CLOCK'):
        gate.GateModel('validation',artifact_dir=tmp_path)
    with pytest.raises(ValueError,match='INVALID_GATE_STAGE'):
        gate.GateModel('test2026',artifact_dir=tmp_path)
