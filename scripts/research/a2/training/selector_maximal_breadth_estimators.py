"""C14 current-state learner adapter; no data, selection, risk or result I/O.

The controller owns the frozen 216 columns (six qualified hybrid heads: 228), chronological label maturity, exact
200-pair geometry, weighted scaler, calibration, capacities and durable ledger.
All component calls are counted separately. Native ranking outputs stay margins.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
import importlib
import math
import warnings
from pathlib import Path
import numpy as np
import pandas as pd

FEATURE_COUNT = 216
C14_PAIR = "C14_PAIR"
SINGLE_FULL_U32 = "SINGLE_FULL_U32"
SINGLE_FEATURE_COUNT = 32
SINGLE_HYBRID_U34 = "SINGLE_HYBRID_U34"
SINGLE_PROFILES = (SINGLE_FULL_U32, SINGLE_HYBRID_U34)
SINGLE_RISK_COLUMNS = ("native_family_marginal_H5_variance", "covariance_with_equal_weight_full_U")
SINGLE_WEIGHT_POLICY = "N/(D*N_t); mean-one rows; equal total mass per decision date"
RISK_FEATURE_COUNT = 228
HYBRID_PARADIGMS = ("RIDGE", "HGB", "XGB", "CAT", "MLP", "QUANTILE_HGB")
CAPACITIES = ("LOW", "MID", "HIGH")
SEEDS = (20260928, 20260929, 20260930)
QUANTILES = (.1, .5, .9)
PARADIGMS = ("RIDGE", "ELASTIC_NET", "HUBER", "LOGIT", "LINEAR_SVM", "EBM",
    "RF", "EXTRA_TREES", "HGB", "XGB", "LGB", "CAT", "MLP", "RESNET",
    "FT_TRANSFORMER", "PAIRWISE_RANKER", "LISTWISE_MLP", "LAMBDAMART",
    "QUANTILE_HGB", "GAUSSIAN_MLP", "MT_RIDGE", "MT_EXTRA_TREES", "MT_MLP")
STOCHASTIC = ("EBM", "RF", "EXTRA_TREES", "CAT", "MLP", "RESNET",
    "FT_TRANSFORMER", "PAIRWISE_RANKER", "LISTWISE_MLP", "GAUSSIAN_MLP",
    "MT_EXTRA_TREES", "MT_MLP")
NEURAL = ("MLP", "RESNET", "FT_TRANSFORMER", "LISTWISE_MLP", "GAUSSIAN_MLP", "MT_MLP")
MULTITASK = ("MT_RIDGE", "MT_EXTRA_TREES", "MT_MLP")
MARGINS = ("LINEAR_SVM", "PAIRWISE_RANKER", "LAMBDAMART")
TORCH_ROOT = Path("D:/us-tech-quant-envs/frozen_dependency_snapshots/development_contexts/fast3_minute_inventory_r1/fast3_torch_cpu/Lib/site-packages")
WEIGHT_POLICY = "date mass one; all 20x10 pairs equal 1/200; no rescale to N or target weighting"
OWNER = "scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/predictors.py"

def _role(role):
    aliases = {"ELASTIC":"ELASTIC_NET", "EXTRA":"EXTRA_TREES", "FT":"FT_TRANSFORMER",
        "FTTRANSFORMER":"FT_TRANSFORMER", "GAUSSIAN":"GAUSSIAN_MLP",
        "PAIRWISE":"PAIRWISE_RANKER", "LISTWISE":"LISTWISE_MLP"}
    role = aliases.get(role, role)
    if role not in PARADIGMS: raise ValueError("UNREGISTERED_C14_PARADIGM")
    return role

def _feature_count(role, count, representation=C14_PAIR):
    if representation in SINGLE_PROFILES:
        expected=32 if representation==SINGLE_FULL_U32 else 34
        if count!=expected: raise ValueError("SINGLE_EXACT_BASE32_OR_HYBRID34_REQUIRED")
        if representation==SINGLE_HYBRID_U34 and _role(role) not in HYBRID_PARADIGMS:
            raise ValueError("ONLY_SIX_SINGLE_HYBRID_HEADS_ALLOW34")
        return count
    if representation != C14_PAIR: raise ValueError("UNKNOWN_SELECTOR_REPRESENTATION")
    if count not in (FEATURE_COUNT,RISK_FEATURE_COUNT):raise ValueError("FROZEN_216_OR_228_FEATURE_COUNT_REQUIRED")
    if count==RISK_FEATURE_COUNT and _role(role) not in HYBRID_PARADIGMS:
        raise ValueError("ONLY_SIX_FROZEN_HYBRID_HEADS_ALLOW_228_FEATURES")
    return int(count)


def component_specs(role):
    role = _role(role)
    return [dict(seed=s, quantile=q) for s in (SEEDS if role in STOCHASTIC else SEEDS[:1])
            for q in (QUANTILES if role == "QUANTILE_HGB" else (None,))]

def capacity_specs(runtime=None, *, input_feature_count=FEATURE_COUNT, representation=C14_PAIR):
    """Pure frozen configuration; no imports of retired runtimes or estimators."""
    _feature_count("RIDGE", input_feature_count, representation)
    out = {}
    for role in (PARADIGMS if representation==SINGLE_FULL_U32 or input_feature_count==FEATURE_COUNT else HYBRID_PARADIGMS):
        out[role] = {}
        for cap, factor, rounds, depth, width, epochs, leaves in zip(
                CAPACITIES, (10., 1., .1), (64,128,256), (3,4,5),
                (32,64,128), (10,20,30), (15,31,63)):
            p = {}
            base = role.removeprefix("MT_")
            if base == "RIDGE": p = dict(alpha=100.*factor, solver="lsqr", tol=1e-6)
            elif base == "ELASTIC_NET": p = dict(alpha=1e-6*factor, l1_ratio=.35,
                max_iter=2500, tol=1e-5, selection="cyclic", precompute=True, random_state=SEEDS[0])
            elif base == "HUBER": p = dict(epsilon=1.35, alpha=1e-4*factor, max_iter=500, tol=1e-5)
            elif base == "LOGIT": p = dict(C=.3/factor, max_iter=400, solver="lbfgs", random_state=SEEDS[0])
            elif base == "LINEAR_SVM": p = dict(C=.3/factor, max_iter=2500,
                tol=1e-4, dual=False, loss="squared_hinge", random_state=SEEDS[0])
            elif base == "EBM": p = dict(max_rounds=rounds, max_leaves=(3,5,7)[CAPACITIES.index(cap)],
                min_samples_leaf=100, interactions=4, outer_bags=1, inner_bags=0,
                smoothing_rounds=0, interaction_smoothing_rounds=0, validation_size=0,
                early_stopping_rounds=0, learning_rate=.05, n_jobs=2, random_state=SEEDS[0])
            elif base in ("RF","EXTRA_TREES"): p = dict(n_estimators=rounds, max_depth=depth,
                min_samples_leaf=100, max_features=1., n_jobs=2, random_state=SEEDS[0])
            elif base in ("HGB","QUANTILE_HGB"): p = dict(max_iter=rounds, max_depth=depth,
                max_leaf_nodes=leaves, min_samples_leaf=100, learning_rate=.05,
                l2_regularization=1., early_stopping=False, random_state=SEEDS[0])
            elif base in ("XGB","PAIRWISE_RANKER"): p = dict(n_estimators=rounds, max_depth=depth,
                min_child_weight=20, learning_rate=.05, subsample=1., colsample_bytree=1.,
                reg_lambda=1., tree_method="hist", n_jobs=2, random_state=SEEDS[0], verbosity=0)
            elif base in ("LGB","LAMBDAMART"): p = dict(n_estimators=rounds, max_depth=depth,
                num_leaves=(8,16,32)[CAPACITIES.index(cap)], min_child_samples=100,
                learning_rate=.05, reg_lambda=1., n_jobs=2, random_state=SEEDS[0],
                deterministic=True, force_col_wise=True, verbosity=-1)
            elif base == "CAT": p = dict(iterations=rounds, depth=depth, learning_rate=.05,
                l2_leaf_reg=3., thread_count=2, random_seed=SEEDS[0],
                verbose=False, allow_writing_files=False)
            else:
                p = dict(hidden=width, epochs=epochs, batch_size=64 if role=="FT_TRANSFORMER" else 512,
                    learning_rate=.001, weight_decay=.0001, feature_clip=[-8.,8.],
                    gradient_clip_norm=5., threads=2, dropout=0., residual_blocks=2,
                    token_dim=(16,32,64)[CAPACITIES.index(cap)], heads=2, layers=1,
                    feedforward_dim=(32,64,128)[CAPACITIES.index(cap)],
                    sinkhorn_iterations=20, sinkhorn_temperature=.1,
                    gaussian_log_sigma_clip=[-12.,2.], sigma_floor=1e-6)
            kind = ("O3_SOFT_OPTIONAL_MATCHING_UTILITY" if role=="LISTWISE_MLP" else
                "O2_BINARY_LOG_LOSS" if role=="LOGIT" else "O2_SQUARED_HINGE_SIGN" if role=="LINEAR_SVM" else
                "O1_EDGE_RELEVANCE_PAIRWISE_SURROGATE" if role=="PAIRWISE_RANKER" else
                "O1_EDGE_RELEVANCE_LAMBDARANK_SURROGATE" if role=="LAMBDAMART" else
                "QUANTILE_PINBALL" if role=="QUANTILE_HGB" else
                "GAUSSIAN_NLL" if role=="GAUSSIAN_MLP" else
                "EQUAL_MEAN_FOUR_TASK_MSE" if role in MULTITASK else "O1_MSE")
            out[role][cap] = dict(params=p, loss_kind=kind, selection_kind="OOF_BRIER_SIGN" if role in MARGINS else "O2_BRIER" if role=="LOGIT" else kind,
                input_features=input_feature_count, outputs=4 if role in MULTITASK else
                    2 if role=="GAUSSIAN_MLP" else 1,
                seed_policy=list(SEEDS if role in STOCHASTIC else SEEDS[:1]),
                quantiles=list(QUANTILES) if role=="QUANTILE_HGB" else [],
                target_standardization="NONE", row_weight=WEIGHT_POLICY,
                capacity_owner=OWNER, scientific_retry=0, checkpoint="FINAL_FIT_OR_FINAL_EPOCH",
                output_kind="margin" if role in MARGINS else "prob" if role=="LOGIT" else
                    "distribution" if role=="GAUSSIAN_MLP" else "quantile" if role=="QUANTILE_HGB" else
                    "tasks_equal_mean" if role in MULTITASK else
                    "utility_score_relative_to_dummy_zero" if role=="LISTWISE_MLP" else "point",
                backend_fit_calls=1, internal_rounds_or_epochs=epochs if role in NEURAL else
                    rounds if base in ("EBM","RF","EXTRA_TREES","HGB","XGB","LGB","CAT","PAIRWISE_RANKER","LAMBDAMART","QUANTILE_HGB") else None,
                internal_ebm_bags=p.get("outer_bags"), hard_matching_training_calls=0,
                relevance_transform="floor(average pct-rank * 5) clipped [0,4]" if role in ("PAIRWISE_RANKER","LAMBDAMART") else None)
    if representation in SINGLE_PROFILES:
        for role, capacities in out.items():
            for spec in capacities.values():
                spec.update(representation=representation, row_weight=SINGLE_WEIGHT_POLICY,
                    scaled_nan_policy="ZERO_AFTER_PAST_WEIGHTED_STANDARD_SCALER; no added channels",
                    ranking_group="COMPLETE_LEGAL_MATURE_SECURITY_DAY_KEYS_BY_DECISION_DATE",
                    final_selection="NATIVE_SCORE_DESC_UID_ASC_TOP20_NO_POSITIVITY_FILTER")
                if representation==SINGLE_HYBRID_U34: spec["risk_feature_order"]=list(SINGLE_RISK_COLUMNS)
                if role == "LISTWISE_MLP":
                    spec.update(loss_kind="FULL_DAY_TOP20_MASS_CROSS_ENTROPY",
                        selection_kind="NEGATIVE_FULL_DAY_TOP20_MEAN_TARGET", output_kind="native_logit",
                        listwise_owner="selector_sufficiency_estimators.date_balanced_listwise_loss",
                        boundary_labels="FULL_TRAIN_GROUP_TARGET_DESC_UID_ASC_FIRST20")
                elif role in ("PAIRWISE_RANKER", "LAMBDAMART"):
                    spec.update(selection_kind="NEGATIVE_FULL_DAY_TOP20_MEAN_TARGET")
    return out

specs = capacity_specs

def _groups(groups, n, representation=C14_PAIR):
    if isinstance(groups, (list,tuple)) and groups and all(np.asarray(x).ndim == 1 for x in groups):
        result = [np.asarray(x) for x in groups]
    else:
        labels = np.asarray(groups)
        if labels.shape != (n,): raise ValueError("COMPLETE_DATE_GROUPS_REQUIRED")
        result = [np.flatnonzero(labels == label) for label in pd.unique(labels)]
    if representation not in (C14_PAIR,*SINGLE_PROFILES): raise ValueError("UNKNOWN_SELECTOR_REPRESENTATION")
    if any(g.dtype.kind not in "iu" or (len(g)!=200 if representation==C14_PAIR else len(g)<1) for g in result):
        raise ValueError("ALL_200_CANONICAL_PAIRS_PER_DATE_REQUIRED" if representation==C14_PAIR else "NONEMPTY_COMPLETE_SINGLE_DATE_GROUPS_REQUIRED")
    if not result or not np.array_equal(np.sort(np.concatenate(result)), np.arange(n)):
        raise ValueError("GROUPS_MUST_COVER_INPUT_EXACTLY_ONCE")
    return [g.astype(np.int64,copy=False) for g in result]

def _input(X, y, w, groups, role, feature_count=FEATURE_COUNT, representation=C14_PAIR):
    x, target, weights = np.asarray(X,float), np.asarray(y,float), np.asarray(w,float)
    if representation in SINGLE_PROFILES:
        if np.isinf(x).any(): raise ValueError("SINGLE_INFINITE_FEATURE_FORBIDDEN")
        x=np.where(np.isnan(x),0.,x)
    if x.ndim!=2 or x.shape[1]!=feature_count or not len(x) or not np.isfinite(x).all():
        raise ValueError(f"FINITE_CURRENT_{feature_count}_FEATURES_REQUIRED")
    expected=(len(x),4) if role in MULTITASK else (len(x),)
    if target.shape!=expected or not np.isfinite(target).all(): raise ValueError("COMPLETE_FROZEN_TARGET_REQUIRED")
    gs=_groups(groups,len(x),representation)
    if representation in SINGLE_PROFILES:
        expected_weights=np.empty(len(x),float)
        for g in gs: expected_weights[g]=len(x)/(len(gs)*len(g))
        if weights.shape!=(len(x),) or not np.isfinite(weights).all() or not np.allclose(weights,expected_weights,rtol=0,atol=1e-12):
            raise ValueError("SINGLE_MEAN_ONE_DATE_BALANCED_WEIGHTS_REQUIRED")
    elif weights.shape!=(len(x),) or not np.isfinite(weights).all() or not np.allclose(weights,.005,rtol=0,atol=1e-12):
        raise ValueError("DATE_ONE_PAIR_WEIGHTS_NO_RESCALE_REQUIRED")
    return x,target,weights,gs

def _torch():
    try: torch=importlib.import_module("torch")
    except (ImportError,OSError) as e: raise RuntimeError("BLOCKED_DEPENDENCY_TORCH") from e
    if str(TORCH_ROOT).replace("\\","/").lower() not in str(torch.__file__).replace("\\","/").lower():
        raise RuntimeError("BLOCKED_DEPENDENCY_UNPINNED_TORCH_ORIGIN")
    return torch

def _network(role, spec):
    torch=_torch(); nn=torch.nn; p=spec["params"]; h=p["hidden"]; outputs=spec["outputs"]; features=spec["input_features"]
    if role=="RESNET":
        class Residual(nn.Module):
            def __init__(self):
                super().__init__(); self.net=nn.Sequential(nn.LayerNorm(h),nn.Linear(h,h),nn.ReLU(),nn.Linear(h,h))
            def forward(self,x): return x+self.net(x)
        return nn.Sequential(nn.Linear(features,h),
            *[Residual() for _ in range(p["residual_blocks"])],nn.LayerNorm(h),nn.ReLU(),nn.Linear(h,outputs))
    if role=="FT_TRANSFORMER":
        class FT(nn.Module):
            def __init__(self):
                super().__init__(); d=p["token_dim"]
                self.token_weight=nn.Parameter(torch.empty(features,d))
                self.token_bias=nn.Parameter(torch.zeros(features,d)); self.cls=nn.Parameter(torch.zeros(1,1,d))
                nn.init.normal_(self.token_weight,std=.02)
                layer=nn.TransformerEncoderLayer(d_model=d,nhead=p["heads"],dim_feedforward=p["feedforward_dim"],
                    dropout=0.,activation="gelu",batch_first=True,norm_first=True)
                self.transformer=nn.TransformerEncoder(layer,num_layers=p["layers"],enable_nested_tensor=False)
                self.output=nn.Sequential(nn.LayerNorm(d),nn.ReLU(),nn.Linear(d,outputs))
            def forward(self,x):
                tokens=x[:,:,None]*self.token_weight[None,:,:]+self.token_bias[None,:,:]
                return self.output(self.transformer(torch.cat((self.cls.expand(len(x),-1,-1),tokens),1))[:,0])
        return FT()
    return nn.Sequential(nn.Linear(features,h),nn.ReLU(),nn.Linear(h,h),nn.ReLU(),nn.Linear(h,outputs))

def soft_optional_matching_utility(scores, truth, groups, *, iterations=20, temperature=.1):
    """30x30 dummy-padded Sinkhorn utility surrogate; no hard assignment solver.

    First ten rows are incumbents; first twenty columns challengers. Twenty
    dummy rows and ten dummy columns allow every incumbent to remain unchanged.
    Complete 200 pairs must be challenger-major/incumbent-minor in each group.
    """
    torch=_torch()
    if iterations!=20 or temperature!=.1: raise ValueError("FROZEN_SOFT_MATCHING_CONFIGURATION")
    if scores.ndim!=1 or truth.shape!=scores.shape: raise ValueError("SCALAR_PAIR_UTILITIES_REQUIRED")
    losses=[]
    for group in groups:
        ix=torch.as_tensor(group,dtype=torch.long,device=scores.device)
        if len(ix)!=200: raise ValueError("COMPLETE_200_PAIR_SOFT_GROUP_REQUIRED")
        logits=scores[ix].reshape(20,10).transpose(0,1)/temperature
        top=torch.cat((logits.clamp(-20.,20.),torch.zeros((10,10),dtype=scores.dtype,device=scores.device)),1)
        logp=torch.cat((top,torch.zeros((20,30),dtype=scores.dtype,device=scores.device)),0)
        for _ in range(iterations):
            logp=logp-torch.logsumexp(logp,dim=1,keepdim=True)
            logp=logp-torch.logsumexp(logp,dim=0,keepdim=True)
        assignment=torch.exp(logp)[:10,:20]
        actual=truth[ix].reshape(20,10).transpose(0,1)
        losses.append(-(assignment*actual).sum()/20.)
    if not losses: raise ValueError("SOFT_MATCHING_DATES_REQUIRED")
    return torch.stack(losses).mean()

@dataclass
class FittedMaximal:
    paradigm: str
    capacity: str
    seed: int
    quantile: float | None
    estimator: object
    metadata: dict
    neural: bool = False

def _native(role,runtime):
    if role=="LINEAR_SVM":
        from sklearn.svm import LinearSVC
        return LinearSVC()
    if runtime is None: raise RuntimeError("BLOCKED_QUALIFIED_NATIVE_RUNTIME_REQUIRED")
    from scripts.research.a2.training.selector_algorithm_objectives import _predictors
    pred=_predictors(runtime)
    names={"RIDGE":"ridge","MT_RIDGE":"ridge","ELASTIC_NET":"elastic","HUBER":"huber","LOGIT":"logistic",
        "EBM":"ebm","RF":"rf","EXTRA_TREES":"extra","MT_EXTRA_TREES":"extra","HGB":"hgb",
        "XGB":"xgb","LGB":"lgb","CAT":"cat","PAIRWISE_RANKER":"xgb_rank","LAMBDAMART":"lgb_rank"}
    return pred._make_estimator(names[role]) if role!="QUANTILE_HGB" else pred._make_estimator("hgb_q",quantile=.1)

def fit(role,capacity,seed,X,y,w,groups,*,runtime=None,horizon=None,quantile=None,on_backend=None,input_feature_count=FEATURE_COUNT,representation=C14_PAIR,boundary_labels=None):
    role=_role(role);feature_count=_feature_count(role,input_feature_count,representation)
    if capacity not in CAPACITIES or dict(seed=seed,quantile=quantile) not in component_specs(role):
        raise ValueError("FROZEN_CAPACITY_SEED_QUANTILE_REQUIRED")
    target=horizon if role in MULTITASK and horizon is not None else y
    x,target,weights,gs=_input(X,target,w,groups,role,feature_count,representation)
    if role=="LOGIT" and len(np.unique(target>0))!=2: raise ValueError("BLOCKED_LABEL_BOTH_CLASSES_REQUIRED")
    if role=="LINEAR_SVM" and len(np.unique(target>0))!=2: raise ValueError("BLOCKED_LABEL_BOTH_CLASSES_REQUIRED")
    spec=copy.deepcopy(capacity_specs(runtime,input_feature_count=feature_count,representation=representation)[role][capacity]);p=spec["params"]
    event=dict(operation="estimator_fit",paradigm=role,capacity=capacity,seed=seed,quantile=quantile,
        outputs=spec["outputs"],backend_fit_calls=1)
    metadata=dict(spec=spec,**event,training_rows=len(x),training_dates=len(gs),
        row_weight_sum=float(weights.sum()),physical_backend_fit_calls=0,scientific_retry=0,
        hard_matching_training_calls=0,output_standardization="NONE")
    def enter():
        if on_backend is not None: on_backend(event)
        metadata["physical_backend_fit_calls"]+=1
    if representation in SINGLE_PROFILES:
        metadata.update(representation=representation, external_rows_dropped=0,
            date_group_sizes=[len(g) for g in gs], missing_channels_added=0)
        if role=="LISTWISE_MLP":
            boundary=np.asarray(boundary_labels,float)
            if boundary.shape!=(len(x),) or not np.isin(boundary,(0.,1.)).all() or any(boundary[g].sum()!=min(20,len(g)) for g in gs):
                raise ValueError("FULL_GROUP_TOP20_LABELS_REQUIRED")
    if role in NEURAL:
        torch=_torch();torch.set_num_threads(2);torch.manual_seed(seed);torch.use_deterministic_algorithms(True)
        model=_network(role,spec);model.train()
        xx=torch.tensor(np.clip(x,*p["feature_clip"]),dtype=torch.float32)
        yy=torch.tensor(target,dtype=torch.float32)
        ww=torch.tensor(weights,dtype=torch.float32) if representation in SINGLE_PROFILES else None
        bb=torch.tensor(boundary,dtype=torch.float32) if representation in SINGLE_PROFILES and role=="LISTWISE_MLP" else None
        optimizer=torch.optim.Adam(model.parameters(),lr=p["learning_rate"],weight_decay=p["weight_decay"])
        gen=torch.Generator().manual_seed(seed);losses=[];updates=0;enter()
        for _ in range(p["epochs"]):
            total=0.;count=0
            if role=="LISTWISE_MLP":
                order=torch.randperm(len(gs),generator=gen).tolist()
                batches=[(gs[j],) for j in order]
            else:
                order=torch.randperm(len(x),generator=gen).numpy()
                batches=[order[i:i+p["batch_size"]] for i in range(0,len(x),p["batch_size"])]
            for batch in batches:
                optimizer.zero_grad()
                if role=="LISTWISE_MLP":
                    ix=np.concatenate(batch);values=model(xx[ix])[:,0]
                    if representation in SINGLE_PROFILES:
                        from scripts.research.a2.training.selector_sufficiency_estimators import date_balanced_listwise_loss
                        loss=date_balanced_listwise_loss(values,bb[ix],[np.arange(len(ix))])
                    else: loss=soft_optional_matching_utility(values,yy[ix],[np.arange(200)])
                else:
                    ix=batch;values=model(xx[ix])
                    if role=="GAUSSIAN_MLP":
                        ls=values[:,1].clamp(*p["gaussian_log_sigma_clip"])
                        row_loss=ls+.5*((yy[ix]-values[:,0])/torch.exp(ls)).square()
                    elif role=="MT_MLP": row_loss=(values-yy[ix]).square().mean(1)
                    else: row_loss=(values[:,0]-yy[ix]).square()
                    loss=(row_loss*ww[ix]).mean() if representation in SINGLE_PROFILES else (values-yy[ix]).square().mean() if role=="MT_MLP" else row_loss.mean()
                if not torch.isfinite(loss): raise RuntimeError("NONFINITE_C14_NEURAL_LOSS_NO_RETRY")
                loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),p["gradient_clip_norm"]);optimizer.step()
                total+=float(loss.detach())*len(ix);count+=len(ix);updates+=1
            losses.append(total/count)
        model.eval();stored={k:v.detach().cpu().numpy().copy() for k,v in model.state_dict().items()}
        metadata.update(epoch_losses=losses,epochs=p["epochs"],updates=updates,
            parameter_count=sum(t.numel() for t in model.parameters()),backend=dict(module="torch",
            version=torch.__version__,origin=str(torch.__file__)),
            soft_matching_transforms=updates if role=="LISTWISE_MLP" and representation==C14_PAIR else 0)
        if representation in SINGLE_PROFILES and role=="LISTWISE_MLP": metadata["full_day_listwise_transforms"]=updates
        fitted=FittedMaximal(role,capacity,seed,quantile,stored,metadata,True)
    else:
        try: estimator=_native(role,runtime)
        except (ImportError,OSError) as exc: raise RuntimeError("BLOCKED_DEPENDENCY_NATIVE_"+role) from exc
        params=copy.deepcopy(p)
        if "random_state" in params:params["random_state"]=seed
        if role=="CAT":params["random_seed"]=seed
        if role=="QUANTILE_HGB":params.update(loss="quantile",quantile=quantile)
        if role=="PAIRWISE_RANKER":params.update(objective="rank:pairwise",
            lambdarank_pair_method="mean",lambdarank_num_pair_per_sample=4)
        if role=="LAMBDAMART":params.update(objective="lambdarank",label_gain=[0,1,3,7,15])
        estimator.set_params(**params)
        fit_x=x;fit_y=(target>0).astype(int) if role in ("LOGIT","LINEAR_SVM") else target
        kwargs=dict(sample_weight=weights)
        if role in ("PAIRWISE_RANKER","LAMBDAMART"):
            order=np.concatenate(gs);fit_x=x[order]
            relevance=np.concatenate([np.minimum(4,np.floor(pd.Series(target[g]).rank(method="average",pct=True).to_numpy()*5)).astype(int) for g in gs])
            fit_y=relevance;kwargs["group"]=[len(g) for g in gs]
            kwargs["sample_weight"]=np.ones(len(gs)) if role=="PAIRWISE_RANKER" else weights[order]
            metadata["native_group_weight"]="UNIT_QUERY" if role=="PAIRWISE_RANKER" else "UNIT_DATE_MASS_ROWS"
        from threadpoolctl import threadpool_limits
        from sklearn.exceptions import ConvergenceWarning
        with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=2):
            warnings.simplefilter("always");enter();estimator.fit(fit_x,fit_y,**kwargs)
        metadata["warnings"]=[dict(category=type(a.message).__name__,message=str(a.message)) for a in caught]
        if any(issubclass(a.category,ConvergenceWarning) for a in caught):raise RuntimeError("UNRESOLVED_CONVERGENCE_NO_RETRY")
        module=importlib.import_module(type(estimator).__module__.split(".",1)[0])
        metadata["backend"]=dict(module=module.__name__,version=getattr(module,"__version__",None),origin=str(module.__file__))
        if role=="EBM":metadata["internal_bags"]=dict(outer=p["outer_bags"],inner=p["inner_bags"],external_backend_calls=1)
        fitted=FittedMaximal(role,capacity,seed,quantile,estimator,metadata)
    predict(fitted,x[:min(len(x),200)])
    return fitted

def _normal(mu,sigma):
    from scipy.special import ndtr,ndtri
    return dict(mu=mu,sigma=sigma,point=mu,prob=ndtr(mu/sigma),
        q10=mu+ndtri(.1)*sigma,q50=mu,q90=mu+ndtri(.9)*sigma)

def predict(fitted,X):
    x=np.asarray(X,float)
    if not isinstance(fitted,FittedMaximal):raise ValueError("C14_FITTED_COMPONENT_REQUIRED")
    role=fitted.paradigm;spec=fitted.metadata["spec"];features=_feature_count(role,spec["input_features"],spec.get("representation",C14_PAIR))
    if spec.get("representation") in SINGLE_PROFILES:
        if np.isinf(x).any(): raise ValueError("SINGLE_INFINITE_PREDICTION_FORBIDDEN")
        x=np.where(np.isnan(x),0.,x)
    if x.ndim!=2 or x.shape[1]!=features or not np.isfinite(x).all():
        raise ValueError("FINITE_C14_PREDICTION_INPUT_REQUIRED")
    if fitted.neural:
        torch=_torch();network=_network(role,spec)
        network.load_state_dict({k:torch.from_numpy(v.copy()) for k,v in fitted.estimator.items()},strict=True);network.eval()
        with torch.no_grad():
            values=np.concatenate([network(torch.tensor(np.clip(x[i:i+spec["params"]["batch_size"]],*spec["params"]["feature_clip"]),dtype=torch.float32)).numpy()
                for i in range(0,len(x),spec["params"]["batch_size"])]) if len(x) else np.empty((0,spec["outputs"]))
        if role=="GAUSSIAN_MLP":
            result=_normal(values[:,0].astype(float),np.maximum(np.exp(np.clip(values[:,1].astype(float),*spec["params"]["gaussian_log_sigma_clip"])),spec["params"]["sigma_floor"]))
        elif role in MULTITASK:result=dict(tasks=values.astype(float),point=values.astype(float).mean(1))
        else:result=dict(point=values[:,0].astype(float))
    elif not len(x):
        if role in MULTITASK:result=dict(tasks=np.empty((0,4)),point=np.empty(0))
        else:result={"margin" if role in MARGINS else "prob" if role=="LOGIT" else f"q{int(fitted.quantile*100)}" if role=="QUANTILE_HGB" else "point":np.empty(0)}
    elif role=="LOGIT":
        classes=np.asarray(fitted.estimator.classes_)
        if not np.array_equal(classes,[0,1]):raise ValueError("POSITIVE_SIGN_CLASS_REQUIRED")
        result=dict(prob=np.asarray(fitted.estimator.predict_proba(x),float)[:,1])
    else:
        values=np.asarray(fitted.estimator.predict(x) if role!="LINEAR_SVM" else fitted.estimator.decision_function(x),float)
        if role in MARGINS:result=dict(margin=values)
        elif role in MULTITASK:result=dict(tasks=values,point=values.mean(1))
        elif role=="QUANTILE_HGB":result={f"q{int(fitted.quantile*100)}":values}
        else:result=dict(point=values)
    if any(not np.isfinite(a).all() or a.shape!=((len(x),4) if k=="tasks" else (len(x),)) for k,a in result.items()):
        raise ValueError("FINITE_COMPLETE_C14_OUTPUTS_REQUIRED")
    if "prob" in result and ((result["prob"]<0).any() or (result["prob"]>1).any()):raise ValueError("VALID_SIGN_PROBABILITY_REQUIRED")
    if "sigma" in result and (result["sigma"]<=0).any():raise ValueError("POSITIVE_NATIVE_SCALE_REQUIRED")
    return result

def combine_predictions(role,components):
    role=_role(role);required={(a["seed"],a["quantile"]) for a in component_specs(role)}
    if set(components)!=required:raise ValueError("ALL_FROZEN_COMPONENTS_REQUIRED_NO_SEED_SELECTION")
    arrays=[components[key] for key in sorted(required,key=lambda k:(k[0],-1 if k[1] is None else k[1]))]
    values=[np.asarray(v,float) for a in arrays for v in a.values()]
    if not values or any(v.ndim not in (1,2) or not np.isfinite(v).all() for v in values):
        raise ValueError("FINITE_REGISTERED_COMPONENT_ARRAYS_REQUIRED")
    if any(v.shape[0]!=values[0].shape[0] for v in values):raise ValueError("IDENTICAL_COMPONENT_ROW_COUNTS_REQUIRED")
    if any(set(a)!=set(arrays[0]) for a in arrays) and role!="QUANTILE_HGB":raise ValueError("IDENTICAL_COMPONENT_OUTPUT_FIELDS_REQUIRED")
    if role in MULTITASK and any(np.asarray(a.get("tasks")).shape!=(len(values[0]),4) for a in arrays):
        raise ValueError("ALL_FOUR_TASK_OUTPUTS_REQUIRED")
    if role=="QUANTILE_HGB":return {k:np.asarray(v,float) for a in arrays for k,v in a.items()}
    if role=="GAUSSIAN_MLP":
        from scipy.special import ndtr
        mus=np.asarray([a["mu"] for a in arrays],float);ss=np.asarray([a["sigma"] for a in arrays],float)
        if mus.ndim!=2 or ss.shape!=mus.shape or (ss<=0).any():raise ValueError("POSITIVE_COMPLETE_NATIVE_NORMAL_COMPONENTS_REQUIRED")
        mu=mus.mean(0);within=(ss*ss).mean(0);between=((mus-mu)**2).mean(0)
        result=dict(mu=mu,point=mu,sigma=np.sqrt(within+between),
            prob=ndtr(mus/ss).mean(0),within_variance=within,between_variance=between)
        for q,name in zip(QUANTILES,("q10","q50","q90")):
            lo=np.min(mus-12*ss,axis=0);hi=np.max(mus+12*ss,axis=0)
            for _ in range(64):
                mid=(lo+hi)/2;c=ndtr((mid[None,:]-mus)/ss).mean(0);lo=np.where(c<q,mid,lo);hi=np.where(c>=q,mid,hi)
            result[name]=(lo+hi)/2
        return result
    result={k:np.mean([np.asarray(a[k],float) for a in arrays],axis=0) for k in arrays[0]}
    if any(not np.isfinite(a).all() for a in result.values()):raise ValueError("FINITE_ENSEMBLE_REQUIRED")
    return result

def fit_component(paradigm,Xscaled,y_scalar,y_tasks,dates,chUID,incUID,cap,seed,q=None,runtime=None,on_fit=None,*,input_feature_count=FEATURE_COUNT):
    clock=pd.DatetimeIndex(pd.to_datetime(dates))
    if clock.hasnans or clock.tz is not None or (clock>=pd.Timestamp("2026-01-01")).any():
        raise ValueError("PRE2026_TRAIN_CLOCK_REQUIRED")
    ch=np.asarray(chUID,object);inc=np.asarray(incUID,object)
    if ch.shape!=(len(clock),) or inc.shape!=(len(clock),):raise ValueError("PAIR_UID_ARRAYS_REQUIRED")
    if not all(isinstance(v,str) and v.strip() and v!="UNKNOWN" for v in np.concatenate((ch,inc))):
        raise ValueError("LEGAL_PAIR_SECURITY_UID_REQUIRED")
    groups=[np.flatnonzero(clock==d) for d in clock.unique().sort_values()]
    for g in groups:
        if len(g)!=200:raise ValueError("EXACT_200_DATE_PAIRS_REQUIRED")
        cg,ig=ch[g],inc[g]
        if len(set(cg))!=20 or len(set(ig))!=10 or set(cg)&set(ig):
            raise ValueError("EXACT_DISJOINT_20x10_UIDS_REQUIRED")
        if len(set(zip(cg,ig)))!=200 or not np.array_equal(cg,np.repeat(cg.reshape(20,10)[:,0],10)) or not np.all(ig.reshape(20,10)==ig.reshape(20,10)[0]):
            raise ValueError("CANONICAL_CHALLENGER_MAJOR_PAIR_ORDER_REQUIRED")
    if _role(paradigm) in MULTITASK:
        scalar=np.asarray(y_scalar,float);tasks=np.asarray(y_tasks,float)
        if scalar.shape!=(len(clock),) or tasks.shape!=(len(clock),4) or not np.isfinite(tasks).all() or not np.isfinite(scalar).all() or not np.allclose(tasks.mean(1),scalar,rtol=1e-10,atol=1e-12):
            raise ValueError("MULTITASK_ORDERED_HORIZONS_EQUAL_MEAN_TARGET_REQUIRED")
    return fit(paradigm,cap,seed,Xscaled,y_scalar,np.full(len(clock),.005),groups,runtime=runtime,
        horizon=y_tasks,quantile=q,on_backend=on_fit,input_feature_count=input_feature_count)

predict_component = predict



def single_top20_labels(y, groups, security_uids):
    """Same complete day labels; UID resolves exact target ties, never an input."""
    truth=np.asarray(y,float);uids=np.asarray(security_uids,object)
    if truth.ndim!=1 or uids.shape!=truth.shape or not np.isfinite(truth).all():
        raise ValueError("FINITE_SINGLE_TARGET_UID_ALIGNMENT_REQUIRED")
    out=np.zeros(len(truth),float)
    for g in _groups(groups,len(truth),SINGLE_FULL_U32):
        order=np.lexsort((uids[g],-truth[g]));out[g[order[:20]]]=1.
    return out


def fit_single_component(paradigm,Xscaled,y_scalar,y_tasks,dates,security_uids,cap,seed,q=None,
        runtime=None,on_fit=None,*,fit_cutoff,label_end_dates,expected_full_day_uids,representation=SINGLE_FULL_U32):
    """Full legal mature single-stock pool; caller owns past scaler and source proof.

    The exact expected day axes are frozen independently of predictions. NaN after
    the past weighted scaler means its past feature mean, with no new channels.
    """
    clock=pd.DatetimeIndex(pd.to_datetime(dates));ends=pd.DatetimeIndex(pd.to_datetime(label_end_dates))
    cutoff=pd.Timestamp(fit_cutoff);uids=np.asarray(security_uids,object)
    if cutoff.tz is not None or cutoff>pd.Timestamp("2026-01-01") or clock.hasnans or clock.tz is not None or not (clock<cutoff).all():
        raise ValueError("SINGLE_STRICT_PRE2026_SIGNAL_CUTOFF_REQUIRED")
    if len(ends)!=len(clock) or ends.hasnans or ends.tz is not None or not (ends<cutoff).all() or not (ends>clock).all():
        raise ValueError("SINGLE_MATURE_LABELS_BEFORE_FIT_REQUIRED")
    if uids.shape!=(len(clock),) or not all(isinstance(v,str) and v.strip() and v!="UNKNOWN" for v in uids):
        raise ValueError("SINGLE_LEGAL_SECURITY_UID_REQUIRED")
    groups=[np.flatnonzero(clock==d) for d in clock.unique().sort_values()]
    expected={pd.Timestamp(k):tuple(v) for k,v in expected_full_day_uids.items()}
    if set(expected)!=set(clock.unique()): raise ValueError("SINGLE_EXACT_ALL_EXPECTED_DATES_REQUIRED")
    for g in groups:
        actual=tuple(uids[g]);day=clock[g[0]]
        if len(set(actual))!=len(g) or actual!=tuple(sorted(actual)) or actual!=expected[day]:
            raise ValueError("SINGLE_EXACT_FULL_DATE_UID_AXIS_REQUIRED")
    scalar=np.asarray(y_scalar,float);tasks=np.asarray(y_tasks,float)
    if _role(paradigm) in MULTITASK and (tasks.shape!=(len(clock),4) or scalar.shape!=(len(clock),) or not np.isfinite(tasks).all() or not np.allclose(tasks.mean(1),scalar,rtol=1e-10,atol=1e-12)):
        raise ValueError("MULTITASK_ORDERED_HORIZONS_EQUAL_MEAN_TARGET_REQUIRED")
    from scripts.research.a2.training.selector_sufficiency_estimators import date_weights
    boundary=single_top20_labels(scalar,groups,uids) if _role(paradigm)=="LISTWISE_MLP" else None
    fitted=fit(paradigm,cap,seed,Xscaled,scalar,date_weights(clock),groups,runtime=runtime,
        horizon=y_tasks,quantile=q,on_backend=on_fit,input_feature_count=32 if representation==SINGLE_FULL_U32 else 34,
        representation=representation,boundary_labels=boundary)
    fitted.metadata.update(fit_cutoff=str(cutoff),max_train_signal=str(clock.max()),
        max_train_label_end=str(ends.max()),identity_input=False,full_date_uid_axis_qualified=True)
    return fitted


def single_training_dag():
    """Pure exact base+MT+fusion reservation graph; no labels, fitting or I/O.

    SVM alone needs Apr warmup for genuine-OOF Platt. Native rankers stay native.
    Jul23 validation selects Jan24; Jan/Jul24 select Jan25. Jan24 selected is
    already one of its three physical capacities, never a second outer refit.
    """
    cuts=("2023-04-01","2023-07-01","2024-01-01","2024-07-01","2025-01-01")
    members=("RIDGE","HGB","XGB","CAT","MLP","QUANTILE_HGB")
    methods=("equal","median","simplex","nnls","ridge_stack","elastic_stack","hgb_stack",
        "mlp_stack","linear_gate","mlp_gate","ridge_then_hgb","hgb_then_ridge")
    nodes=[]
    def add(node,kind,**identity): nodes.append(dict(node_id=node,kind=kind,**identity))
    for c in cuts: add("SCALER|"+c,"SCALER",cutoff=c)
    for role in PARADIGMS:
        for c in (cuts[:-1] if role=="LINEAR_SVM" else cuts[1:-1]):
            for cap in CAPACITIES:
                for component in component_specs(role):
                    add(f"MODEL|{role}|{c}|{cap}|{component['seed']}|{component['quantile']}","ESTIMATOR",role=role,cutoff=c,capacity=cap,**component)
        for component in component_specs(role):
            add(f"MODEL|{role}|{cuts[-1]}|SELECTED|{component['seed']}|{component['quantile']}","ESTIMATOR",role=role,cutoff=cuts[-1],capacity="SELECTED",**component)
            if role in members:
                add(f"MODEL|{role}|{cuts[-1]}|MID|{component['seed']}|{component['quantile']}","ESTIMATOR",role=role,cutoff=cuts[-1],capacity="MID",conditional_alias="SELECTED_CAPACITY_IS_MID_AND_IDENTITY_EXACT",**component)
    for c in cuts[1:]:
        for cap in CAPACITIES if c!=cuts[-1] else ("SELECTED",):
            add(f"PLATT|LINEAR_SVM|{c}|{cap}","CALIBRATOR",cutoff=c,capacity=cap)
    stochastic=("mlp_stack","linear_gate","mlp_gate")
    for year in (2024,2025):
        for method in methods:
            kinds=("META_MODEL","META_SCALER") if method in ("ridge_stack","elastic_stack","hgb_stack","mlp_stack","ridge_then_hgb","hgb_then_ridge") else ()
            if method=="nnls": kinds=("META_MODEL",)
            if method=="simplex": kinds=("META_MODEL","META_TARGET_SCALE")
            if method in ("linear_gate","mlp_gate"): kinds=("META_MODEL","META_SCALER","META_TARGET_SCALE")
            for seed in SEEDS if method in stochastic else SEEDS[:1]:
                suffix=f"|{seed}" if method in stochastic else ""
                for kind in kinds: add(f"{kind}|{method}|{year}{suffix}",kind,method=method,year=year,seed=seed)
    counts={k:sum(n["kind"]==k for n in nodes) for k in sorted({n["kind"] for n in nodes})}
    if len({n["node_id"] for n in nodes})!=len(nodes): raise ValueError("SINGLE_DAG_DUPLICATE")
    return dict(representation=SINGLE_FULL_U32,nodes=nodes,counts=counts,learned_operation_ceiling=len(nodes),
        actual_operations_require_backend_callbacks=True,scientific_retries=0,failed_reservation_refund=False,
        signed_amplitude_fits=0,equal_median_fit_calls=0,native_rank_calibration_fits=0,
        fusion_members=list(members),fusion_methods=list(methods),fusion_oof="FIXED_MID_JUL23_JAN24_JUL24_BEFORE_META_CUTOFF",
        hybrid_separate_ceiling=dict(estimator=120,scaler=24,learned_operations=144,scientific_retries=0),
        all_65_policy_account_ceiling_including_raw=66)
