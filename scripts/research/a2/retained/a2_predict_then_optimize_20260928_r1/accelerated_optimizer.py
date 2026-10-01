"""Numerically equivalent JIT projections; objectives and 80 rounds unchanged."""
from common import *
import numpy as np
from numba import njit
import optimizers as reference

ORIGINAL_PROJECTION=reference.project_box_budget
ORIGINAL_DUAL_PROJECTION=reference._project_capped_probability

@njit(cache=True)
def prox_kernel(values,upper,budget,current,penalty):
    b,n=values.shape;result=np.empty_like(values)
    for j in range(b):
        total=0.
        for i in range(n):
            delta=values[j,i]-current[j,i]
            sign=1. if delta>0 else -1. if delta<0 else 0.
            result[j,i]=min(upper[j,i],max(0.,current[j,i]+sign*max(abs(delta)-penalty[j],0.)))
            total+=result[j,i]
        if total>budget[j]+1e-12:
            lo=0.;hi=max(np.max(values[j])+np.max(np.abs(current[j]))+penalty[j]+1.,1.)
            for k in range(36):
                mid=(lo+hi)/2;total=0.
                for i in range(n):
                    delta=values[j,i]-mid-current[j,i]
                    sign=1. if delta>0 else -1. if delta<0 else 0.
                    total+=min(upper[j,i],max(0.,current[j,i]+sign*max(abs(delta)-penalty[j],0.)))
                if total>budget[j]:lo=mid
                else:hi=mid
            for i in range(n):
                delta=values[j,i]-hi-current[j,i]
                sign=1. if delta>0 else -1. if delta<0 else 0.
                result[j,i]=min(upper[j,i],max(0.,current[j,i]+sign*max(abs(delta)-penalty[j],0.)))
    return result

@njit(cache=True)
def dual_kernel(values,cap):
    b,n=values.shape;q=np.empty_like(values)
    for j in range(b):
        lo=np.min(values[j])-cap;hi=np.max(values[j])
        for k in range(36):
            mid=(lo+hi)/2;total=0.
            for i in range(n):total+=min(cap,max(0.,values[j,i]-mid))
            if total>1.:lo=mid
            else:hi=mid
        total=0.;mid=(lo+hi)/2
        for i in range(n):q[j,i]=min(cap,max(0.,values[j,i]-mid));total+=q[j,i]
        for i in range(n):q[j,i]/=total
    return q

def project_box_budget(values,upper,budget,*,current=None,penalty=0.):
    values=np.asarray(values,float);one=values.ndim==1
    if one:values=values[None,:]
    shape=values.shape
    upper=reference._matrix(upper,shape,.1);current=reference._matrix(current,shape,0.)
    budget=reference._matrix(budget,(shape[0],),.95);penalty=reference._matrix(penalty,(shape[0],),0.)
    if (upper<0).any() or (budget<0).any() or (penalty<0).any():raise ValueError('NEGATIVE_PROJECTION_CONSTRAINT')
    result=prox_kernel(np.ascontiguousarray(values),np.ascontiguousarray(upper),budget,np.ascontiguousarray(current),penalty)
    return result[0] if one else result

def project_capped_probability(values,cap):return dual_kernel(np.ascontiguousarray(values,dtype=float),float(cap))

def enable():
    reference.project_box_budget=project_box_budget
    reference._project_capped_probability=project_capped_probability

def disable():
    reference.project_box_budget=ORIGINAL_PROJECTION
    reference._project_capped_probability=ORIGINAL_DUAL_PROJECTION
