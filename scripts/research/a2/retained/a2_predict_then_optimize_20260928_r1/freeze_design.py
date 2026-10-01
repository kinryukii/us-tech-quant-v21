"""Finite roster lock: no model fitting and no evaluation in this program."""
from common import *
import pandas as pd
import importlib.metadata as metadata
from datetime import datetime, timezone
import shutil

def main():
    if (ROOT/'DESIGN_LOCK.json').exists(): raise RuntimeError('DESIGN_ALREADY_LOCKED')
    features=read(WS/'a2_latest_effective_joint_20260927/models/model_registry.json')['feature_order']
    assert len(features)==32 and len(PROVIDERS)==31 and len(forecasts())==152 and len(strategies())==5053
    source_engine=WS/'a2_buy_sell_cash_multimodel_20260928/engine_v2.py'
    shutil.copyfile(source_engine,ROOT/'engine_v2.py')
    contract=dict(created_utc=datetime.now(timezone.utc).isoformat(),experiment='A2_PREDICT_THEN_OPTIMIZE_R1',
        features=features,seed=20260928,stages={'early':'2024-01-01','validation':'2025-01-01','final':'2026-01-01'},
        target='y_next_open',horizon='signal close t; execute t+1 open; label ends t+2 open',
        training_clip=[-.20,.20],sampling=dict(max_rows=30000,date_balanced=True,key_hash_seed=20260928),
        data_paths=dict(pre2026='input/pre2026.parquet',prices='input/pre2026_prices.parquet'),
        models=PROVIDERS,model_output_objects=dict(point=POINTS,probability=PROBS,quantile=QUANTILES,distribution=DISTRIBUTIONS,rank=RANKERS),
        model_specs=dict(linear=dict(ridge_alpha=10,elastic_alpha=.0001,l1_ratio=.35,huber_epsilon=1.35,huber_alpha=.01,huber_max_iter=500),
          boosted=dict(iterations=100,depth=3,leaves=15,min_leaf=100,l2=5,lr=.05,early_stopping=False),
          randomized_trees=dict(trees=100,depth=6,min_leaf=40),ebm=dict(interactions=0,max_rounds=200,outer_bags=2,validation_size=0,early_stopping_rounds=0,smoothing_rounds=0),
          mlp=dict(hidden=[32,16],epochs=20,early_stopping=False),torch=dict(epochs=12,batch=512,resnet_width=32,resnet_blocks=2,ft_token_dim=8,ft_heads=2,ft_layers=2),
          quantiles=[.1,.5,.9],ngboost=dict(iterations=100,depth=3,distribution='Normal')),
        adapters=dict(probability='train-only positive/negative return amplitude; no probability-as-return',
          quantile='sorted .1/.5/.9; fixed .3/.4/.3 approximate integral plus train residual offset',
          rank='train-only isotonic score-to-return mapping; calibration is fitted in-sample and disclosed',
          robust_point='training residual mean offset, not an assumed conditional mean',
          uncertainty='native distribution/quantiles where present; otherwise training residual normal proxy'),
        coalitions=COALITIONS,fusions=FUSIONS,risks=RISKS,optimizers=OPTIMIZERS,
        cooperation_scope='31 singletons, 11 prespecified structural/output coalitions; no exhaustive power set, no outcome-selected member groups',
        fusion_learning=dict(validation_oof_years=[2024],final_oof_years=[2024,2025],max_rows=20000,
          convex_regularization=.001,ridge_alpha=100,elastic_alpha=.0001,elastic_l1_ratio=.35,
          hgb=dict(max_iter=100,depth=2,leaves=7,min_leaf=100,l2=5,lr=.05),
          mlp=dict(hidden=[8],epochs=40),gates=dict(epochs=80,lr=.01,hidden=8,prior_regularization=.001),
          residual_anchor_rule='first member corrected by HGB; last member corrected by Ridge; both learn OOF residuals'),
        risk_contract=dict(lookback=252,min_observations=126,variance_floor=.0001,unknown_volatility=.08,factors=5,
          scale_targets='conditional clipped next-open squared return; same32featuresandtrainingkeys',
          covariance_cooperation=['equal_lw_oas','equal_pca_fa'],
          scenario_rows=64,scenario_rule='deterministic common pre-cutoff history rank-normal scores, whitening/recoloring to risk covariance, native marginal adaptation; no independent sampling'),
        optimization=dict(support='entire available legal candidate pool ranked by forecast mu, ticker tie break; top20 subject to reserved slots',
          risk_aversion=4,robust_radius=.5,cvar_alpha=.9,cvar_penalty=2,solver_iterations=80,
          solver='finite-iteration projected solver; convergence and feasibility reported separately',
          turnover_penalty=.001,equal_top20='95% equally across eligible top20; fixed exposure comparison; risk parameter canonicalized to none'),
        account=dict(initial_cash=1000000,max_names=20,max_target_weight=.10,max_target_gross=.95,cost_bps=10,
          buy_capacity_fraction=.01,capacity_on_sells=False,signal='close',execution='next open',terminal_liquidation=False,
          missing_input='hold actual units and reserve capital/slots',each_strategy_independent=True),
        evaluation=dict(pre2026='2025 signals 01-02 to12-29, markto12-31',test2026='frozen after all learning; 01-02 to09-22, markto09-24',
          formal_full_pool_test='BLOCKED_IF_ORIGINAL_RULE_POOL_UNKNOWN',qualified_subset_diagnostic=True,blind_test=False,no_test_feedback=True),
        counts=dict(base_output_specs=31,scalar_fit_targets_per_stage=43,base_stages=3,forecasts=152,
          prediction_routes=4712,target_blend_routes=341,total_pto_routes=5053,evaluation_windows=2),
        decision_controls=['cash','REINFORCE','REINFORCE_zero','PPO','PPO_zero'],
        rl=dict(seed=20260928,epochs=4,updates_per_day=1,hidden=[32,16],ppo_clip=.2,learning_rate=.001,
          input='same32features+predecisionownweight+cash; same holding-aware account/cost',scope='independent decision comparison, not an extra PTO fusion/optimizer'),
        excluded=dict(extra_kernel_bayesian_sequence_regime_models='extensions not included in this finite first batch',
          garch_gjr='optional statistical extension not included; finite risk roster fixed to covariance/factor/learned-scale/cooperation',
          all_member_power_set='not in candidate contract; 11 fixed coalitions cover structures and output objects'),
        old_reuse='source data/execution implementation only; old action utility and multi-horizon artifacts fail target/interface compatibility',
        source_engine_sha256=sha(source_engine),runtime={p:metadata.version(p) for p in ['numpy','pandas','scipy','scikit-learn','torch','xgboost','lightgbm','catboost','interpret-core','ngboost']})
    write(ROOT/'contract.json',contract)
    pd.DataFrame(forecasts()).to_csv(ROOT/'FORECAST_ROSTER.csv',index=False)
    frame=pd.DataFrame(strategies()); frame['pre2026_status']='PENDING';frame['test2026_formal_status']='BLOCKED_INPUT_AUDIT_PENDING';frame['test2026_diagnostic_status']='PENDING_GLOBAL_FREEZE'
    frame.to_csv(ROOT/'COMBINATION_COVERAGE.csv',index=False)
    compat=[]
    for p in PROVIDERS:
        for f in ['identity',*FUSIONS]:
            for r in ['none',*RISKS]:
                for o in ['equal_top20',*OPTIMIZERS]:
                    legal=(r=='none')==(o=='equal_top20')
                    compat.append(dict(provider=p,fusion=f,risk=r,optimizer=o,legal=legal,
                      input_adapter='native -> calibrated/approximated return interface',reason='' if legal else 'risk-less optimizer canonicalized; covariance required by risk optimization'))
    pd.DataFrame(compat).to_csv(ROOT/'INPUT_OUTPUT_COMPATIBILITY.csv',index=False)
    write(ROOT/'DESIGN_LOCK.json',dict(created_utc=contract['created_utc'],contract_sha256=sha(ROOT/'contract.json'),
      forecasts_sha256=sha(ROOT/'FORECAST_ROSTER.csv'),strategy_roster_sha256=sha(ROOT/'COMBINATION_COVERAGE.csv'),
      candidate_change_allowed=False,fit_started=False,test2026_evaluation_started=False))
    print(json.dumps(contract['counts']))

if __name__=='__main__': main()
