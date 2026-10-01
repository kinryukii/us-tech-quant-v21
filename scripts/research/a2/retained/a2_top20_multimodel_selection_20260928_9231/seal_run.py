"""Seal completed research, separating training and diagnostic from formal test."""
from pathlib import Path
import hashlib,json
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    verify=json.loads((ROOT/'VERIFICATION.json').read_text(encoding='utf-8'))
    assert verify['status']=='PASS' and len(verify['paths'])==76
    needed=['FINDINGS.md','REPORT.md','TRAINING_SUMMARY.md','METHOD_COVERAGE.json','MODEL_COMPARISON.csv',
            'ENSEMBLE_LAST_SIGNAL_TOP20_RANKINGS.csv','TOP20_RANKINGS.md','DIAGNOSTICS_RECEIPT.json',
            'ENSEMBLE_DIVERSITY_AND_VALIDATION.json','ENSEMBLE_NUMERICAL_PRECISION_NOTE.json',
            'CORE_TESTS.log','INTEGRATION_TESTS.log','VERIFICATION.json','ENVIRONMENT.json']
    assert all((ROOT/p).exists() for p in needed)
    result=dict(completed_utc=datetime.now(timezone.utc).isoformat(),
        training_status='COMPLETE',ensemble_training_status='COMPLETE',
        diagnostic_evaluation_status='COMPLETE_76_FROZEN_PATHS',
        formal_2026_full_pool_test_status='BLOCKED_INPUT_CERTIFICATION',
        formal_2026_full_pool_return=None,
        unresolved=['47,271 UNKNOWN original-universe candidate days; zero complete pool dates',
                    'retrospective qualification and historical vendor arrival times not certified',
                    'GLW event-date/adjusted-feature conflict',
                    'price-index accounting is not certified shareholder total return',
                    '2025 and 2026 historically observed; not untouched blind holdouts'],
        train_cutoff_exclusive='2026-01-01',fit_2026_rows=0,hyperparameter_searches=0,
        test_signal_window=['2026-01-02','2026-09-22'],test_terminal_valuation='2026-09-24',
        comparison_paths=19,cost_scenarios_2026=[5,10,25],validation_cost_2025=10,
        tests_passed=89,production_deployed=False,
        result_sha256={p:sha(ROOT/p) for p in needed})
    (ROOT/'RUN_MANIFEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['training_status','ensemble_training_status','diagnostic_evaluation_status','formal_2026_full_pool_test_status']}))

if __name__=='__main__':main()
