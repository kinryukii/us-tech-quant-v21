import numpy as np
from ensemble_policy import blend_targets,risk_scale

def test_consolidated_names_cash_and_weight_caps():
    m=np.zeros((30,6))
    for i in range(6):m[i*5:(i+1)*5,i]=.1
    w,mean,sd=blend_targets(m,np.ones(6)/6,list(range(30)),slots=17,budget=.7)
    assert (w>0).sum()==17 and w.max()<=.1 and w.sum()<=.7
    assert w.sum()<mean.sum() # discarded opinions remain cash

def test_disagreement_reduces_exposure_only():
    m=np.array([[.1,0,.1,0,.1,0],[.05]*6])
    normal,_,_=blend_targets(m,np.ones(6)/6,['A','B'])
    cautious,_,_=blend_targets(m,np.ones(6)/6,['A','B'],consensus=True)
    assert cautious[0]<normal[0] and abs(cautious[1]-normal[1])<1e-12

def test_risk_scale_respects_locked_positions():
    c=np.eye(3)*.04
    w=np.array([.1,.1]);locked=np.array([.04])
    s=risk_scale(w,locked,c)
    assert 0<s<1 and np.r_[w*s,locked]@c@np.r_[w*s,locked]<=.015**2+1e-12
    assert risk_scale(w,[.2],c)==0
