"""Pure arithmetic connection from frozen OOF labels to frozen Ridge coefficients.

This never optimizes coefficients and never calls any estimator fit method.
"""
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import json
import numpy as np
import joblib
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent/'a2_multimodel_joint_20260928'
sys.path.insert(0,str(ROOT))
import evaluate
from threadpoolctl import threadpool_limits

guard=evaluate.forbid_fitting()
receipt=json.loads((ROOT/'ensemble_artifacts/meta/FIT_RECEIPT.json').read_text(encoding='utf-8'))
output=[]
for record in receipt['fits']:
    matrices=[];targets=[]
    for year in record['oof_years']:
        with np.load(receipt['oof_sampling'][str(year)]['matrix_path'],allow_pickle=False) as z:
            matrices.append(z['features']);targets.append(z['target'])
    x=np.concatenate(matrices);y=np.concatenate(targets)
    model=joblib.load(record['artifact']);scaler,ridge=model[0],model[-1]
    with threadpool_limits(limits=2):
        z=(x-scaler.mean_)/scaler.scale_
        centered_z=z-z.mean(axis=0)
        centered_y=y-y.mean()
        residual=centered_z@ridge.coef_-centered_y
        rhs=centered_z.T@centered_y
        gradient=centered_z.T@residual+ridge.alpha*ridge.coef_
    output.append(dict(stage=record['stage'],rows=len(y),alpha=ridge.alpha,solver=ridge.solver,solver_tolerance=ridge.tol,
        intercept_minus_implied_y_mean=float(ridge.intercept_-(y.mean()-z.mean(axis=0)@ridge.coef_)),
        normal_equation_gradient_l2=float(np.linalg.norm(gradient)),
        normal_equation_gradient_max_abs=float(np.max(np.abs(gradient))),
        normal_equation_rhs_l2=float(np.linalg.norm(rhs)),
        relative_normal_equation_residual=float(np.linalg.norm(gradient)/max(np.linalg.norm(rhs),np.finfo(float).tiny)),
        explanation='Arithmetic stationarity diagnostic for saved standardized Ridge coefficients and stated OOF labels; lsqr is approximate, and this is not retraining or original runtime attestation.'))
assert guard['attempts']==0
(HERE/'ridge_label_coefficient_stationarity.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(output))
