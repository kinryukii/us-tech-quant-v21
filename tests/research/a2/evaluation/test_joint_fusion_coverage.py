"""Synthetic binding and frozen OOF output reuse for thin fusion runner."""
import json
from pathlib import Path
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_fusion_coverage as runner

class Task:
    def __init__(self,root):self.root=root
    def out(self,relative):return self.root/relative
    def read(self,relative):return json.loads(self.out(relative).read_text())
    def write(self,relative,obj):
        path=self.out(relative);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj))

def test_reader_binds_hash_and_column_projection_before_pages(tmp_path,monkeypatch):
    task=Task(tmp_path);path=task.out("OOF/synthetic.parquet");path.parent.mkdir()
    frame=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]),"ticker":["A"],"mu":[.01],"unused":[999.]})
    frame.to_parquet(path,index=False)
    task.write("receipts/synthetic.json",{"sha256":runner.digest(path)})
    out,dep=runner.read_bound_oof(task,"OOF/synthetic.parquet","receipts/synthetic.json",["signal_date","ticker","mu"])
    assert list(out)==["signal_date","ticker","mu"]
    assert dep["sha256"]==runner.digest(path)
    frame["mu"]+=1;frame.to_parquet(path,index=False)
    with pytest.raises(ValueError,match="hash mismatch"):
        runner.read_bound_oof(task,"OOF/synthetic.parquet","receipts/synthetic.json",["signal_date","ticker","mu"])

def test_future_physical_content_denied_by_reader_before_projection(tmp_path):
    task=Task(tmp_path);path=task.out("OOF/synthetic.parquet");path.parent.mkdir()
    pd.DataFrame({"signal_date":pd.to_datetime(["2026-01-02"]),"mu":[1.]}).to_parquet(path,index=False)
    task.write("receipts/synthetic.json",{"sha256":runner.digest(path)})
    with pytest.raises(ValueError):runner.read_bound_oof(task,"OOF/synthetic.parquet","receipts/synthetic.json",["signal_date","mu"])

def test_output_reuse_checks_identity_and_bytes_preserves_unregistered(tmp_path):
    task=Task(tmp_path);task.out("OOF").mkdir()
    frame=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]),"mu":[1.]})
    identity={"model_sha256":"synthetic-fitted-digest","input_binding_sha256":"bound"}
    first=runner.JointFusionCoverage._save(task,"B_META","equal",2023,frame,identity,{"status":"SYNTHETIC"})
    second=runner.JointFusionCoverage._save(task,"B_META","equal",2023,frame,identity,{"status":"SYNTHETIC"})
    assert first==second
    with pytest.raises(RuntimeError,match="identity/bytes changed"):
        runner.JointFusionCoverage._save(task,"B_META","equal",2023,frame,{"model_sha256":"changed"},{})
    frame["mu"]+=1;frame.to_parquet(task.out("OOF/B_META_equal_2023.parquet"),index=False)
    with pytest.raises(RuntimeError,match="identity/bytes changed"):
        runner.JointFusionCoverage._save(task,"B_META","equal",2023,frame,identity,{})
