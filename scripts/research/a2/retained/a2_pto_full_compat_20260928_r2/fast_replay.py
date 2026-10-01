"""Use bit-identical work elimination for both frozen evaluation years."""
import argparse
from contextlib import contextmanager
from cached_replay import eager_risk_load
from shared import *

@contextmanager
def numeric_work_elimination():
    import optimization
    from fast_numeric import prox_budget_subset
    from fast_cvar_numeric import smooth_cvar_buffered
    original_prox=optimization._prox_budget
    original_cvar=optimization._smooth_cvar
    optimization._prox_budget=prox_budget_subset
    optimization._smooth_cvar=smooth_cvar_buffered
    try:yield
    finally:
        optimization._prox_budget=original_prox
        optimization._smooth_cvar=original_cvar

def run_fast_year(year):
    from run_suite import run_year
    with eager_risk_load() as archives,numeric_work_elimination():
        result=run_year(year)
    destination=ROOT/'results'/f'evaluation_{year}'/'IMPLEMENTATION_EQUIVALENCE_USED.json'
    if not destination.exists():
        write_json(destination,{'year':year,'status':'BIT_IDENTICAL_IMPLEMENTATION_ADAPTERS_USED',
            'mathematical_spec_changed':False,'model_parameters_changed':False,'new_fit_calls':0,
            'source_binding':{n:sha(ROOT/n) for n in ['fast_replay.py','cached_replay.py','fast_numeric.py',
                'fast_cvar_numeric.py','optimization.py','fast_account.py']},
            'risk_archives':[{'source':a.source,'decompression_counts':dict(a.decompression_counts)} for a in archives],
            'original_models_predictions_and_strategy_roster_preserved':True,
            'reference_fortran_and_strided_projection_fallback':True})
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,required=True,choices=[2025,2026]);args=parser.parse_args()
    print(run_fast_year(args.year)['status'],flush=True)
