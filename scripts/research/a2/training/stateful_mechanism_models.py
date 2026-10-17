"""R10 bounded mechanism-model consumer of retained predictor/loss owners.

No research I/O, source activation, scaler fitting, target clipping or account
execution. Root supplies already transformed legal rows and owns fit ACK/budgets.
Torch training reuses the retained fit_torch code with private globals/constants;
only the necessary four-head output and arbitrary-channel projection are added.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from types import CodeType, FunctionType
import hashlib
import importlib
import json
import warnings
import numpy as np
from scipy.special import ndtr
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits
from scripts.research.a2.training import stateful_values as values

NATIVE_PATH=values.NATIVE
EXTENSION_PATH=Path(__file__).with_name("stateful_value_extensions.py")
CAPACITIES=("LOW","MID","HIGH")
SEEDS=(20260928,20260929,20260930)
FAMILIES=("Ridge","ElasticNet","Huber","Logistic","HGB","XGB","LGB",
          "CatBoost","ExtraTrees","MLP","ResNet","FTTransformer",
          "HGBQuantile","NGBoost","GaussianMLP")
STOCHASTIC=frozenset(("CatBoost","MLP","ResNet","FTTransformer","GaussianMLP",
                     "TCN","GRU","LSTM","GaussianMLP4H"))
_IDS=dict(Ridge="ridge",ElasticNet="elastic",Huber="huber",Logistic="logistic",
          HGB="hgb",XGB="xgb",LGB="lgb",CatBoost="cat",ExtraTrees="extra",
          MLP="mlp",ResNet="resnet",FTTransformer="fttransformer",
          HGBQuantile="hgb_q",NGBoost="ngboost",GaussianMLP="mlp_dist")
_SEQ={"TCN":"tcn","GRU":"gru","LSTM":"lstm"}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def source_pins():
    return dict(adapter_sha256=sha(__file__),native_sha256=sha(NATIVE_PATH),
                extension_sha256=sha(EXTENSION_PATH),fusion_native_sha256=sha(NATIVE_PATH.with_name("fusion_models.py")),
                fusion_owner_sha256=sha(Path(__file__).with_name("stateful_fusion.py")))

def parameters(family,capacity):
    if capacity not in CAPACITIES: raise ValueError("CAPACITY_NOT_FROZEN")
    i=CAPACITIES.index(capacity); rounds=(60,100,180)[i];depth=(2,3,5)[i]
    width=(16,32,64)[i];epochs=(12,24,48)[i]
    if family=="Ridge": return dict(alpha=(100.,10.,1.)[i],solver="auto")
    if family=="ElasticNet": return dict(alpha=(.001,.0001,.00001)[i],l1_ratio=.35,
                                         max_iter=2500,tol=1e-5,selection="cyclic")
    if family=="Huber": return dict(epsilon=1.35,alpha=(.1,.01,.001)[i],max_iter=500)
    if family=="Logistic": return dict(C=(.1,.3,1.)[i],max_iter=400,solver="lbfgs")
    if family in ("HGB","HGBQuantile"):
        return dict(max_iter=rounds,max_depth=depth,max_leaf_nodes=(7,15,31)[i],
                    min_samples_leaf=100,l2_regularization=5.,learning_rate=.05,
                    early_stopping=False)
    if family=="XGB":
        return dict(n_estimators=rounds,max_depth=depth,max_leaves=(7,15,31)[i],
                    min_child_weight=100.,reg_lambda=5.,learning_rate=.05,
                    tree_method="hist",n_jobs=2,subsample=1.,colsample_bytree=1.,verbosity=0)
    if family=="LGB":
        return dict(n_estimators=rounds,max_depth=depth,num_leaves=(7,15,31)[i],
                    min_child_samples=100,reg_lambda=5.,learning_rate=.05,n_jobs=2,
                    subsample=1.,colsample_bytree=1.,verbosity=-1,deterministic=True,
                    force_col_wise=True)
    if family=="CatBoost":
        return dict(iterations=rounds,depth=depth,min_data_in_leaf=100,
                    l2_leaf_reg=5.,learning_rate=.05,thread_count=2,verbose=False,
                    allow_writing_files=False,bootstrap_type="No")
    if family=="ExtraTrees":
        return dict(n_estimators=rounds,max_depth=(4,6,10)[i],min_samples_leaf=40,
                    max_features=1.,n_jobs=2)
    if family=="MLP":
        return dict(hidden_layer_sizes=(width,width//2),activation="relu",solver="adam",
                    alpha=.01,batch_size=512,max_iter=epochs,n_iter_no_change=epochs+1,
                    early_stopping=False,learning_rate_init=.001)
    if family=="NGBoost":
        return dict(n_estimators=rounds,learning_rate=.05,base_depth=depth,
                    base_min_samples_leaf=100,minibatch_frac=1.,col_sample=1.,
                    tol=0.,early_stopping_rounds=None)
    if family in ("ResNet","FTTransformer","GaussianMLP","GaussianMLP4H",*_SEQ):
        return dict(width=width,epochs=epochs,learning_rate=.001,weight_decay=.01,
                    batch_size=512,gradient_clip=2.,target_scale=.1,final_epoch_only=True,
                    resnet_blocks=2,ft_token_dim=width//4,ft_heads=2,ft_layers=2,
                    recurrent_layers=1,tcn_dilations=[1,2,4,8],lookbacks=[5,10,20],
                    device="cpu",threads=2,early_stopping=False)
    if family=="Cox":
        return dict(penalizer=(1.,.1,.01)[i],l1_ratio=0.,duration_col="duration",
                    event_col="event",weights_col="weight",prediction_age=7.)
    raise ValueError("UNKNOWN_MECHANISM_FAMILY:"+str(family))

def specifications():
    families=(*FAMILIES,*_SEQ,"Cox","GaussianMLP4H")
    return dict(schema="R10_MECHANISM_MODELS_R1",families=list(FAMILIES),
                optional=list(families[len(FAMILIES):]),capacities=list(CAPACITIES),
                stochastic_seeds=list(SEEDS),deterministic_seed=SEEDS[0],
                configurations={f:{c:parameters(f,c) for c in CAPACITIES} for f in families},
                preprocessing="ROOT_SHARED_TRAIN_ONLY_DATE_WEIGHTED_SCALER;NO_MODEL_SCALER",scaled_families=list(SCALED),
                scaler_operation="mechanism_scaler",sequence_scaler_weights="repeat(row_weight/L);observed-cells-only",
                fusion=fusion_specifications(),
                target_clip="NONE",quantiles=[.1,.5,.9],seed_ensemble="MEAN_NOT_BEST",
                gaussian4h="FOUR_MARGINAL_GAUSSIANS;MEAN_POINT_ONLY_NO_JOINT_SIGMA",
                source_pins=source_pins())

ALIASES={f.replace("_","").lower():f for f in (*FAMILIES,*_SEQ,"Cox","GaussianMLP4H")}
ALIASES.update({"fttransformer":"FTTransformer","hgbquantile":"HGBQuantile","gaussianmlp":"GaussianMLP","gaussianmlp4h":"GaussianMLP4H"})
SCALED_FAMILIES=frozenset(("Ridge","ElasticNet","Huber","Logistic","MLP","ResNet","FTTransformer","GaussianMLP","GaussianMLP4H",*_SEQ,"Cox"))

ACTION_FAMILIES=("ridge","elasticnet","huber","logistic","hgb","xgb","lgb","catboost","extratrees","mlp","resnet","ft_transformer","hgb_quantile","ngboost","gaussian_mlp")
SCALED=("ridge","elasticnet","huber","logistic","mlp","resnet","ft_transformer","gaussian_mlp","gaussian_mlp4h","tcn","gru","lstm","cox")

def canonical_family(name):
    key=str(name).replace("_","").replace("-","").replace(" ","").lower()
    if key not in ALIASES: raise ValueError("UNKNOWN_MECHANISM_FAMILY:"+str(name))
    return ALIASES[key]

def _node(model_id,payload):
    if isinstance(model_id,str):
        try: node=json.loads(model_id)
        except (ValueError,TypeError):
            if isinstance(payload,dict) and "family" in payload:
                try: canonical_family(model_id); node={"family":model_id}
                except ValueError: node={"audit_id":model_id}
            else: node={"family":model_id}
    elif isinstance(model_id,dict): node=dict(model_id)
    else: raise ValueError("MODEL_NODE_SCHEMA")
    if not isinstance(node,dict): raise ValueError("MODEL_NODE_SCHEMA")
    if isinstance(payload,dict):
        for k in ("family","capacity","seed","objective","lookback","source_pins"):
            if k in payload:
                if k in node and (canonical_family(node[k])!=canonical_family(payload[k]) if k=="family" else node[k]!=payload[k]): raise ValueError("MODEL_NODE_PAYLOAD_CONFLICT:"+k)
                node[k]=payload[k]
    node["family"]=canonical_family(node.get("family"))
    if node.get("capacity") not in CAPACITIES: raise ValueError("CAPACITY_NOT_FROZEN")
    seed=node.get("seed")
    if type(seed) is not int or seed not in SEEDS: raise ValueError("SEED_NOT_FROZEN")
    if node["family"] not in STOCHASTIC and seed!=SEEDS[0]:
        raise ValueError("DETERMINISTIC_EXTRA_SEED_NOT_AUTHORIZED")
    if "source_pins" in node and node["source_pins"]!=source_pins():
        raise ValueError("MODEL_SOURCE_PINS_CHANGED")
    if node["family"] in _SEQ and node.get("lookback") not in (5,10,20):
        raise ValueError("SEQUENCE_LOOKBACK_NOT_FROZEN")
    return node

def _arrays(node,X,target,weight):
    x=np.asarray(X,float);y=np.asarray(target,float);w=np.asarray(weight,float)
    sequence=node["family"] in _SEQ
    if not len(x) or x.ndim!=(3 if sequence else 2) or not np.isfinite(x).all():
        raise ValueError("FINITE_ALREADY_TRANSFORMED_X_REQUIRED")
    if sequence and x.shape[1]!=node["lookback"]: raise ValueError("SEQUENCE_LOOKBACK_SHAPE")
    expected=(len(x),4) if node["family"]=="GaussianMLP4H" else (len(x),)
    if y.shape!=expected or not np.isfinite(y).all(): raise ValueError("FINITE_TARGET_SHAPE_REQUIRED")
    if w.shape!=(len(x),) or not np.isfinite(w).all() or np.any(w<=0):
        raise ValueError("POSITIVE_DATE_WEIGHTS_REQUIRED")
    return x,y,w

def _replace_constants(code,fn):
    constants=tuple(_replace_constants(v,fn) if isinstance(v,CodeType)
                    else fn(v) for v in code.co_consts)
    return code.replace(co_consts=constants)

def _clone(function,globals_=None,const_fn=None):
    code=function.__code__ if const_fn is None else _replace_constants(function.__code__,const_fn)
    env=dict(function.__globals__);env.update(globals_ or {})
    return FunctionType(code,env,function.__name__,function.__defaults__,function.__closure__)

def _torch_bind(node,native,dependencies,n_channels=None):
    from scripts.research.a2.training import stateful_value_extensions as extension
    torch=extension._torch(dependencies)
    par=parameters(node["family"],node["capacity"]);width=par["width"];kind=node["family"]
    # No global mutation: original owner code remains byte/source identical.
    change=lambda v: width if type(v) is int and v==32 else (width//2 if type(v) is int and v==16 else (width//4 if type(v) is int and v==8 else v))
    factory=_clone(native.make_torch_network,const_fn=change)
    seq_factory=None
    if kind in _SEQ:
        seq_factory=_clone(extension._network,{"HIDDEN":width},
                    lambda v:n_channels if type(v) is int and v==64 else v)
    def make(kind_,n_features):
        if kind in _SEQ: return seq_factory(_SEQ[kind],torch)
        base=factory(_IDS.get(kind,"mlp_dist"),n_features)
        if kind=="GaussianMLP4H":
            base[-1]=torch.nn.Linear(width//2,8)
        return base
    def loss(kind_,prediction,target,weights):
        if kind=="GaussianMLP4H":
            return sum(native.torch_loss("mlp_dist",prediction[:,2*h:2*h+2],
                                        target[:,h],weights) for h in range(4))/4
        return native.torch_loss(_IDS.get(kind,kind_.lower()),prediction,target,weights)
    fit=_clone(native.fit_torch,{"SEED":node["seed"],"make_torch_network":make,"torch_loss":loss},
               lambda v:par["epochs"] if type(v) is int and v==12 else v)
    predict_fn=_clone(native.predict_torch,{"make_torch_network":make})
    return fit,predict_fn,torch

@dataclass
class MechanismModel:
    node:dict
    estimator:object
    metadata:dict
    dependencies:tuple=()
    def predict(self,X): return predict(self,X)

def fit(model_id,X,payload,*,quantile=None,dependencies=(),on_fit_started=None):
    if not isinstance(payload,dict) or not {"target","weights"}.issubset(payload):
        raise ValueError("MECHANISM_TARGET_WEIGHT_PAYLOAD_REQUIRED")
    node=_node(model_id,payload);x,y,w=_arrays(node,X,payload["target"],payload["weights"])
    family=node["family"];par=parameters(family,node["capacity"]);parts=[]
    def started(name):
        if on_fit_started is not None: on_fit_started(name)
        parts.append(name)
    native=values._native(dependencies);objective=str(node.get("objective","ADVANTAGE")).upper()
    classifier=family=="Logistic" or (objective=="HAZARD" and family in ("HGB","XGB","CatBoost","MLP"))
    info=dict(node=node,parameters=par,training_rows=len(x),actual_fit_components=parts,
              actual_fit_count=0,scaler_fit_count=0,target_clip="NONE",source_pins=source_pins(),
              feature_shape=list(x.shape[1:]),warnings=[],family=family,classifier=classifier)
    with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=2):
        warnings.simplefilter("always")
        if family in ("ResNet","FTTransformer","GaussianMLP","GaussianMLP4H",*_SEQ):
            f,_,_= _torch_bind(node,native,dependencies,x.shape[2] if x.ndim==3 else None)
            started("MECHANISM_TORCH_PREDICTOR")
            obj,receipt=f(family,x,y,w)
            if receipt["epochs"]!=par["epochs"]: raise RuntimeError("FIXED_EPOCH_CONTRACT")
            info.update(receipt)
        elif family=="Cox":
            module=importlib.import_module("lifelines")  # Existing dependency only; no fallback/install.
            import pandas as pd
            duration=np.asarray(payload.get("duration"),float);event=np.asarray(payload.get("event"))
            if duration.shape!=(len(x),) or event.shape!=(len(x),) or not np.isfinite(duration).all() or np.any(duration<=0) or not np.isin(event,[0,1]).all():
                raise ValueError("COX_EVENT_CENSOR_SCHEMA_REQUIRED")
            cols=[f"x{i}" for i in range(x.shape[1])]
            frame=pd.DataFrame(x,columns=cols);frame["duration"]=duration;frame["event"]=event;frame["weight"]=w
            obj=module.CoxPHFitter(penalizer=par["penalizer"],l1_ratio=0.)
            started("MECHANISM_COX")
            obj.fit(frame,duration_col="duration",event_col="event",weights_col="weight",show_progress=False)
            info["cox_features"]=cols
        elif family=="HGBQuantile":
            qq=(.1,.5,.9) if quantile is None else (float(quantile),)
            if any(q not in (.1,.5,.9) for q in qq): raise ValueError("QUANTILE_NOT_FROZEN")
            obj={}
            for q in qq:
                head=native.estimator("hgb_q",quantile=q);head.set_params(**par,random_state=node["seed"])
                started("MECHANISM_QUANTILE_Q"+str(int(q*100)))
                head.fit(x,y,sample_weight=w);obj[q]=head
            info["quantiles"]=list(qq)
        else:
            mid=_IDS[family]
            if classifier and family!="Logistic": mid += "_cls"
            obj=native.estimator(mid)
            pp=dict(par)
            if family=="NGBoost":
                base=obj.Base
                pp.pop("early_stopping_rounds",None)
                base.set_params(max_depth=pp.pop("base_depth"),
                                min_samples_leaf=pp.pop("base_min_samples_leaf"),
                                random_state=node["seed"])
                pp["Base"]=base;pp["random_state"]=node["seed"]
            elif family=="CatBoost": pp["random_seed"]=node["seed"]
            elif "random_state" in obj.get_params(deep=False): pp["random_state"]=node["seed"]
            obj.set_params(**pp)
            if classifier:
                yy=(y>0).astype(int) if objective!="HAZARD" else y
                if not np.array_equal(np.unique(yy),[0,1]): raise ValueError("CLASSIFIER_REQUIRES_BOTH_CLASSES")
            else: yy=y
            started("MECHANISM_ESTIMATOR")
            obj.fit(x,yy,sample_weight=w)
            if family=="MLP" and obj.n_iter_!=par["max_iter"]: raise RuntimeError("MLP_FIXED_EPOCH_CONTRACT")
            if family=="NGBoost" and len(obj.base_models)!=par["n_estimators"]: raise RuntimeError("NGBOOST_FIXED_ROUND_CONTRACT")
    info["warnings"]=[dict(category=c.category.__name__,message=str(c.message)) for c in caught]
    if family in ("Ridge","ElasticNet","Huber","Logistic","Cox") and any(issubclass(c.category,ConvergenceWarning) for c in caught):
        raise RuntimeError("OPTIMIZER_DID_NOT_CONVERGE_NO_SCIENTIFIC_RETRY")
    info["actual_fit_count"]=len(parts)
    return MechanismModel(node,obj,info,tuple(map(str,dependencies))),info

def predict(model,X):
    if isinstance(model,FusionModel): return predict_fusion(model,X)
    if not isinstance(model,MechanismModel): raise ValueError("MECHANISM_ARTIFACT_TYPE")
    if model.metadata["source_pins"]!=source_pins(): raise ValueError("ARTIFACT_SOURCE_CUSTODY_CHANGED")
    node=model.node;family=node["family"];x=np.asarray(X,float)
    if x.ndim!=len(model.metadata["feature_shape"])+1 or tuple(x.shape[1:])!=tuple(model.metadata["feature_shape"]) or not np.isfinite(x).all():
        raise ValueError("PREDICTION_FEATURE_SHAPE_OR_FINITE")
    out={k:None for k in ("mean","probability","q10","q50","q90","sigma")}
    native=values._native(model.dependencies)
    if family in ("ResNet","FTTransformer","GaussianMLP","GaussianMLP4H",*_SEQ):
        _,fn,torch=_torch_bind(node,native,model.dependencies,x.shape[2] if x.ndim==3 else None)
        raw=fn(model.estimator,x) if len(x) else np.empty((0,8 if family=="GaussianMLP4H" else 2))
        if family in ("GaussianMLP","GaussianMLP4H"):
            a=np.asarray(raw,float).reshape(len(x),4 if family=="GaussianMLP4H" else 1,2)
            mu=a[:,:,0]*.1
            sd=(np.logaddexp(0,a[:,:,1])+1e-3)*.1
            if family=="GaussianMLP4H":
                out.update(mean=mu.mean(1),mean_h=mu,sigma_h=sd,
                           marginal_quantiles=np.stack([mu-1.2815515655446004*sd,mu,mu+1.2815515655446004*sd],axis=-1))
            else:
                mu=mu[:,0];sd=sd[:,0]
                out.update(mean=mu,sigma=sd,probability=ndtr(mu/sd),q10=mu-1.2815515655446004*sd,q50=mu,q90=mu+1.2815515655446004*sd)
        else: out["mean"]=np.asarray(raw,float).reshape(-1)*.1
    elif family=="Cox":
        import pandas as pd
        frame=pd.DataFrame(x,columns=model.metadata["cox_features"])
        out["probability"]=1-model.estimator.predict_survival_function(frame,times=[7.]).iloc[0].to_numpy(float)
    elif model.metadata["classifier"]:
        classes=list(model.estimator.classes_)
        out["probability"]=np.asarray(model.estimator.predict_proba(x),float)[:,classes.index(1)]
    elif family=="HGBQuantile":
        predictions={q:np.asarray(v.predict(x),float) for q,v in model.estimator.items()}
        if set(predictions)=={.1,.5,.9}:
            out["raw_quantiles"]=np.column_stack([predictions[q] for q in (.1,.5,.9)])
            rearranged=np.sort(out["raw_quantiles"],axis=1)
            predictions={q:rearranged[:,i] for i,q in enumerate((.1,.5,.9))}
        for q,key in ((.1,"q10"),(.5,"q50"),(.9,"q90")): out[key]=predictions.get(q)
        # Median is a native point location, not an inferred conditional mean.
        out["point"]=out["q50"]
        out["point_statistic"]="NATIVE_MEDIAN"
    elif family=="NGBoost":
        dist=model.estimator.pred_dist(x);mu=np.asarray(dist.params["loc"],float);sd=np.asarray(dist.params["scale"],float)
        out.update(mean=mu,sigma=sd,probability=ndtr(mu/sd),q10=np.asarray(dist.ppf(.1),float),q50=np.asarray(dist.ppf(.5),float),q90=np.asarray(dist.ppf(.9),float))
    else: out["mean"]=np.asarray(model.estimator.predict(x),float)
    for key,value in out.items():
        if isinstance(value,np.ndarray) and not np.isfinite(value).all(): raise RuntimeError("NONFINITE_NATIVE_OUTPUT:"+key)
    return out

def raw_predict(model,X):
    p=predict(model,X)
    if p["mean"] is not None: return p["mean"]
    if p.get("point") is not None: return p["point"]
    if p["probability"] is not None: return p["probability"]
    raise ValueError("NO_POINT_OR_SIGN_INTERFACE")

def fit_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed):
    """The existing values owner receives and ACKs every actual fit component."""
    def started(component):
        pipe.send(("FIT_START",component))
        if pipe.recv() is not True: raise RuntimeError("PARENT_REJECTED_MECHANISM_FIT_BUDGET")
    try:
        if operation=="mechanism_scaler":
            model,metadata=fit_weighted_scaler(x,y,observed=observed,on_fit_started=started)
        elif operation=="mechanism":
            model,metadata=fit(model_id,x,y,quantile=quantile,dependencies=dependencies,on_fit_started=started)
        else: raise ValueError("MECHANISM_OPERATION_NOT_FROZEN")
        pipe.send(("RESULT",model,metadata))
    except BaseException as exc:
        pipe.send(("ERROR",type(exc).__name__,str(exc)))
    finally: pipe.close()


FUSION_METHODS=("equal","median","nnls","convex","stack_ridge","stack_elastic",
                "stack_hgb","stack_mlp","gate_linear","gate_mlp",
                "residual_first_hgb","residual_last_ridge")

def fusion_specifications():
    return dict(methods=list(FUSION_METHODS),
                expert_packet=["Ridge","Equal(Ridge,HGB)","HGB"],
                independent_expert_count=2,virtual_expert_fit_count=0,
                stochastic_methods=["stack_mlp","gate_mlp"],stochastic_seeds=list(SEEDS),
                other_seed=SEEDS[0],shared_scaler_views=["expert","state","combined"],
                scaler_fit_by_worker=0,native_mlp_epochs=40,native_gate_epochs=80,
                uncertainty="POINT_ONLY;NATIVE_INSAMPLE_RESIDUAL_SCALE_IS_NOT_AUTHORITY",
                native_source_sha256=sha(NATIVE_PATH.with_name("fusion_models.py")),
                fitted_components_per_group_year=14,shared_scalers_per_group_year=3,
                primary_total=68,sequence_S3_total=8,total=76)

@dataclass
class FusionModel:
    method:str
    estimator:object
    metadata:dict
    dependencies:tuple=()
    def predict(self,X): return predict_fusion(self,X)

def _frozen_scale_fit(self,*args,**kwargs):
    # Root owns train-only fitting; borrower must not modify shared state.
    if not len(args) or np.asarray(args[0]).shape[1]!=self.n_features_in_:
        raise ValueError("PREFITTED_FUSION_SCALER_VIEW_SHAPE")
    return self

def fit_fusion(model_id,X,payload,*,dependencies=(),on_fit_started=None):
    import copy
    from types import MethodType
    from scripts.research.a2.training import stateful_fusion as owner
    if not isinstance(payload,dict): raise ValueError("FUSION_PAYLOAD_REQUIRED")
    method=payload.get("method",model_id)
    if method not in FUSION_METHODS: raise ValueError("FUSION_METHOD_NOT_FROZEN")
    seed=payload.get("seed",SEEDS[0])
    if type(seed) is not int or seed not in SEEDS or (method not in ("stack_mlp","gate_mlp") and seed!=SEEDS[0]):
        raise ValueError("FUSION_SEED_NOT_FROZEN")
    x=np.asarray(X,float);y=np.asarray(payload.get("target"),float)
    w=np.asarray(payload.get("weights"),float);state=np.asarray(payload.get("state"),float)
    if x.shape!=(len(y),3) or state.shape!=(len(y),4) or w.shape!=(len(y),) or len(y)<2:
        raise ValueError("FUSION_PACKET_SHAPE")
    if any(not np.isfinite(v).all() for v in (x,y,w,state)) or np.any(w<=0):
        raise ValueError("FUSION_FINITE_POSITIVE_WEIGHT")
    if not np.array_equal(x[:,1],(x[:,0]+x[:,2])/2):
        raise ValueError("VIRTUAL_EXPERT_NOT_EXACT_EQUAL")
    parts=[]
    def started(name):
        if on_fit_started is not None: on_fit_started(name)
        parts.append(name)
    with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=2):
        warnings.simplefilter("always")
        if method in ("equal","median"):
            obj=owner.FixedFusion(method)
        elif method=="nnls":
            # Same owner function, weighted least-squares arguments only.
            original=owner.nnls;root=np.sqrt(w)
            fn=_clone(owner._fit_arrays,{"nnls":lambda a,b:original(a*root[:,None],b*root)})
            obj=fn(method,x,y,state,w,started,dependencies)
        else:
            native=owner._native(dependencies)
            if method.startswith("gate_"):
                from scripts.research.a2.training import stateful_value_extensions as extension
                extension._torch(dependencies)
            if method.startswith("stack_"): view="expert";matrix=x
            elif method.startswith("gate_"): view="state";matrix=state
            elif method.startswith("residual_"): view="combined";matrix=np.column_stack([x,state])
            else: view=None;matrix=None
            borrowed=[]
            def scale():
                shared=payload.get("shared_scalers",{}).get(view)
                if shared is None or getattr(shared,"n_features_in_",None)!=matrix.shape[1]:
                    raise ValueError("FUSION_TRAIN_ONLY_SHARED_SCALER_UNBOUND")
                identity=payload.get("shared_scaler_input_sha256",{}).get(view)
                actual=hashlib.sha256(np.ascontiguousarray(matrix,dtype=float).tobytes()).hexdigest()
                if identity is not None and identity!=actual:
                    raise ValueError("FUSION_SCALER_INPUT_IDENTITY_CHANGED")
                item=copy.deepcopy(shared);item.fit=MethodType(_frozen_scale_fit,item);borrowed.append(item)
                return item
            def constructor(original,name):
                def create(*a,**kw):
                    item=original(*a,**kw);bound=item.fit
                    def fit_(*args,**kwargs):
                        started(name);delattr(item,"fit");return bound(*args,**kwargs)
                    item.fit=fit_
                    return item
                return create
            def gate(*args,**kwargs):
                started("FUSION_GATE_PREDICTOR");return native.Gate(*args,**kwargs)
            def minimize(*args,**kwargs):
                started("FUSION_SIMPLEX");return native.minimize(*args,**kwargs)
            env={"StandardScaler":scale,"Gate":gate,"minimize":minimize}
            for name in ("Ridge","ElasticNet","HistGradientBoostingRegressor","MLPRegressor"):
                env[name]=constructor(getattr(native,name),"FUSION_"+name)
            fn=_clone(native.Fusion.fit,env)
            obj=native.Fusion(method,seed=seed)
            try: fn(obj,x,y,state,w)
            finally:
                for item in borrowed:
                    if "fit" in item.__dict__:delattr(item,"fit")
            if method=="stack_mlp" and obj.model.steps[-1][1].n_iter_!=40:
                raise RuntimeError("FUSION_MLP_FIXED40_NOT_COMPLETED")
    meta=dict(method=method,seed=seed,training_rows=len(y),
              actual_fit_count=len(parts),actual_fit_components=parts,scaler_fit_count=0,
              native_parameters=fusion_specifications(),source_pins=source_pins(),
              warnings=[dict(category=c.category.__name__,message=str(c.message)) for c in caught],
              native_insample_sigma="DIAGNOSTIC_ONLY_NOT_POLICY_AUTHORITY",
              target_clip="NONE",independent_expert_count=2)
    if method in ("nnls","convex","stack_ridge","stack_elastic") and any(issubclass(c.category,ConvergenceWarning) for c in caught):
        raise RuntimeError("FUSION_OPTIMIZER_DID_NOT_CONVERGE_NO_RETRY")
    return FusionModel(method,obj,meta,tuple(map(str,dependencies))),meta

def predict_fusion(model,X):
    if model.metadata["source_pins"]!=source_pins(): raise ValueError("FUSION_SOURCE_CUSTODY_CHANGED")
    if not isinstance(X,dict) or not {"experts","state"}.issubset(X):
        raise ValueError("FUSION_PREDICTION_REQUIRES_EXPERTS_STATE")
    x=np.asarray(X["experts"],float);state=np.asarray(X["state"],float)
    if x.ndim!=2 or x.shape[1]!=3 or state.shape!=(len(x),4) or not np.isfinite(x).all() or not np.isfinite(state).all():
        raise ValueError("FUSION_PREDICTION_PACKET")
    if not np.array_equal(x[:,1],(x[:,0]+x[:,2])/2): raise ValueError("VIRTUAL_EXPERT_NOT_EXACT_EQUAL")
    if model.method.startswith("gate_"):
        from scripts.research.a2.training import stateful_value_extensions as extension
        extension._torch(model.dependencies)
    values_=np.asarray(model.estimator.predict(x,state),float)
    if values_.shape!=(len(x),) or not np.isfinite(values_).all(): raise RuntimeError("NONFINITE_FUSION_POINT")
    return dict(mean=values_,probability=None,q10=None,q50=None,q90=None,sigma=None)

def fusion_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed):
    def started(component):
        pipe.send(("FIT_START",component))
        if pipe.recv() is not True: raise RuntimeError("PARENT_REJECTED_FUSION_FIT_BUDGET")
    try:
        if operation!="fusion":raise ValueError("FUSION_OPERATION_REQUIRED")
        model,meta=fit_fusion(model_id,x,y,dependencies=dependencies,on_fit_started=started)
        pipe.send(("RESULT",model,meta))
    except BaseException as exc:pipe.send(("ERROR",type(exc).__name__,str(exc)))
    finally:pipe.close()


def fit_weighted_scaler(X,payload,*,observed=None,on_fit_started=None):
    from sklearn.preprocessing import StandardScaler
    if not isinstance(payload,dict) or "weights" not in payload:
        raise ValueError("SCALER_DATE_WEIGHTS_REQUIRED")
    x=np.asarray(X,float);w=np.asarray(payload["weights"],float)
    if x.ndim not in (2,3) or not len(x) or w.shape!=(len(x),) or not np.isfinite(w).all() or np.any(w<=0):
        raise ValueError("SCALER_INPUT_WEIGHT_SHAPE")
    mask=np.isfinite(x) if observed is None else np.asarray(observed)
    if mask.shape!=x.shape or mask.dtype!=np.dtype(bool) or not np.isfinite(x[mask]).all():
        raise ValueError("SCALER_OBSERVED_MASK")
    if np.isinf(x).any():raise ValueError("SCALER_INFINITE_INPUT")
    if x.ndim==3:
        flat=np.where(mask,x,np.nan).reshape(-1,x.shape[-1])
        fw=np.repeat(w/x.shape[1],x.shape[1])
    else:
        flat=np.where(mask,x,np.nan);fw=w
    if not np.isfinite(flat).any(axis=0).all():raise ValueError("NO_TRAIN_ONLY_OBSERVED_MEAN")
    if on_fit_started is not None:on_fit_started("MECHANISM_DATE_WEIGHTED_SCALER")
    obj=StandardScaler().fit(flat,sample_weight=fw)
    if not np.isfinite(obj.mean_).all() or not np.isfinite(obj.scale_).all():
        raise RuntimeError("NONFINITE_TRAIN_ONLY_SCALER")
    meta=dict(actual_fit_count=1,actual_fit_components=["MECHANISM_DATE_WEIGHTED_SCALER"],
              scaler_fit_count=1,training_rows=len(x),observed_cells=int(mask.sum()),
              input_shape=list(x.shape),weights="DATE_EQUAL_REPEAT_DIVIDE_LENGTH" if x.ndim==3 else "DATE_EQUAL",
              source_pins=source_pins(),target_clip="NOT_APPLICABLE")
    return obj,meta
