"""Focused metadata-list regression and exact engineering-source lineage guards."""
import ast
import copy
import json
from pathlib import Path
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_native_coverage as native
from scripts.research.a2.evaluation import joint_fusion_coverage as meta

def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')

def frame():
    return pd.DataFrame({'signal_date':pd.to_datetime(['2021-02-01','2021-02-02']), 'ticker':['SYNTH1','SYNTH2'], 'source_cutoff':pd.Timestamp('2021-01-01'), 'source_label_mature_max':pd.Timestamp('2020-12-30'), 'ridge__raw':[.1,.2], 'y_open5':[.2,.3], 'label_mature_date':pd.to_datetime(['2021-02-09','2021-02-10']), 'label_end_date':pd.to_datetime(['2021-02-08','2021-02-09'])})

def test_native_fit_key_is_unchanged_after_later_prior_append():
    prior=[{'year':2021,'sha256':'synthetic'}]
    key=native.bridge_fit_key({'design_sha256':'design','fitted_source_sha256':{}},prior,frame(),{'native_name':'ridge'}, {})
    before=native._json_sha(key)
    prior.append({'year':2022,'sha256':'later'})
    assert len(key['prior_native_fold_dependencies'])==1
    assert native._json_sha(key)==before

def test_residual_calibration_key_is_unchanged_after_later_composite_append():
    tree=ast.parse(Path(meta.__file__).read_text(encoding='utf-8'))
    assignment=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='bridge_key' for t in n.targets))
    prior=[{'oof_path':'B_RESID_synthetic_2022.parquet','sha256':'synthetic'}]
    env={'spec':{},'sources':{},'composite_deps':prior,'prepared':frame(),'_frame_sha':native._frame_sha}
    key=eval(compile(ast.Expression(assignment.value),'<actual residual identity expression>','eval'),env)
    before=native._json_sha(key)
    prior.append({'oof_path':'B_RESID_synthetic_2023.parquet','sha256':'later'})
    assert len(key['prior_true_composite_OOF_dependencies'])==1 and native._json_sha(key)==before

@pytest.fixture
def lineage(tmp_path):
    root=tmp_path/'synthetic_task';dump(root/'INPUT_BINDING.json',{'synthetic':True});dump(root/'RUN_CONFIG.json',{'synthetic':True})
    changes=[];current={};frozen={}
    for i,source in enumerate((Path(native.__file__).resolve(),Path(meta.__file__).resolve())):
        old=root/f'receipts/snapshot_{i}.py';old.parent.mkdir(parents=True,exist_ok=True);old.write_text('# synthetic old source\n')
        item={'path':str(source),'old_sha256':native.digest(old),'new_sha256':native.digest(source),'snapshot_path':str(old)}
        changes.append(item);current[str(source)]=item['new_sha256'];frozen[str(source)]=item['old_sha256']
    extra=root/'unchanged.py';extra.write_text('# unchanged synthetic source\n');current[str(extra)]=frozen[str(extra)]=native.digest(extra)
    metadata=root/'receipts/metadata.json';validation=root/'receipts/validation.json'
    dump(metadata,{'status':'DETERMINISTIC_ORIGINAL_KEY_METADATA_RESTORED','records_repaired':158,'all_frozen_receipt_keys_reconstructed_exactly':True,'actual_fit_units_before':968,'actual_fit_units_after':968,'model_or_OOF_files_written':0,'fit_calls':0,'source_changes':changes})
    dump(validation,{'passed':True,'fit_calls':0})
    repair={'status':'VALIDATED_EXACT_ENGINEERING_SOURCE_REPAIR','input_binding_sha256':native.digest(root/'INPUT_BINDING.json'),'run_config_sha256':native.digest(root/'RUN_CONFIG.json'),'source_changes':changes,'metadata_repair_receipt':{'path':str(metadata),'sha256':native.digest(metadata)},'validation_receipt':{'path':str(validation),'sha256':native.digest(validation)}}
    path=root/'receipts/FIVE_DAY_ENGINEERING_SOURCE_REPAIR.json';dump(path,repair)
    return root,current,frozen,repair,path

def test_exact_engineering_lineage_preserves_scientific_source_identity(lineage):
    root,current,frozen,_,_=lineage
    scientific,executed=native.scientific_source_binding(root,current,frozen)
    assert scientific==frozen and executed==current

@pytest.mark.parametrize('case',['missing_lineage','changed_snapshot','unrelated_source','failed_validation'])
def test_lineage_denies_any_unverified_transition(lineage,case):
    root,current,frozen,repair,path=lineage
    if case=='missing_lineage':path.unlink()
    elif case=='changed_snapshot':Path(repair['source_changes'][0]['snapshot_path']).write_text('# altered')
    elif case=='unrelated_source':current[next(s for s in current if s.endswith('unchanged.py'))]='unapproved'
    else:
        dump(Path(repair['validation_receipt']['path']),{'passed':False,'fit_calls':0})
        repair['validation_receipt']['sha256']=native.digest(repair['validation_receipt']['path']);dump(path,repair)
    with pytest.raises(RuntimeError,match='RESUME_BLOCKED_SOURCE_LINEAGE'):
        native.scientific_source_binding(root,current,frozen)

def test_completion_proof_never_reads_later_pipeline_state(tmp_path,monkeypatch):
    root=tmp_path/'C_synthetic';dump(root/'BASE_COMPLETION.json',{'phase':'BASE_ATTEMPTS_COMPLETE','years':list(range(2021,2026)),'candidates':40,'test2026_read':False,'finished_at':'2026-10-01T10:00:00Z'})
    dump(root/'COOPERATION_COMPLETION.json',{'phase':'COOPERATION_ATTEMPTS_COMPLETE','test2026_read':False,'finished_at':'2026-10-01T11:00:00Z'})
    dump(root/'PIPELINE_STATE.json',{'forbidden_economic_state':'must not read'})
    seen=[];old=native._read_json
    def read(path):
        assert Path(path).name!='PIPELINE_STATE.json'
        seen.append(Path(path).name);return old(path)
    monkeypatch.setattr(native,'_read_json',read)
    assert native._native_wave_metadata(root,None)['complete']
    assert set(seen)=={'BASE_COMPLETION.json','COOPERATION_COMPLETION.json'}
