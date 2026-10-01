"""Exact account equivalence after immutable forecast lookup acceleration."""
from common import *
import pandas as pd
import time
import run_replays as r

def main():
    r.initialize(2025)
    receipts=[]
    for method in ['mv','robust','equal_top20']:
        spec=next(s for s in strategies() if s['forecast_id']=='single__ridge' and s['risk']==('none' if method=='equal_top20' else 'diag') and s['optimizer']==method)
        policy=r.Policy(spec);start=time.monotonic()
        result=r.run_replay(r.ENV['prices'],r.ENV['calendar'],r.ENV['panel'],policy,candidate=spec['strategy_id'],
            cost_bps=10,capacity_fraction=.01,signal_start=r.ENV['metadata']['signal_start'],signal_end=r.ENV['metadata']['signal_end'],
            signal_asof=r.ENV['asofs'],operational_exits_by_signal=r.ENV['ops'],prepared_inputs=r.ENV['prepared'])
        # equal_top20 support correction has no held-only keys in this 2025 path;
        # the old integration ledger already uses the corrected legal rule.
        folder=ROOT/'evaluation_2025'/spec['strategy_id']
        for name in r.LEDGERS:
            pd.testing.assert_frame_equal(getattr(result,name),pd.read_parquet(folder/(name+'.parquet')),check_exact=True)
        receipts.append(dict(strategy_id=spec['strategy_id'],all_ten_ledgers_exact=True,seconds=time.monotonic()-start))
        print(json.dumps(receipts[-1]),flush=True)
    write(ROOT/'REPLAY_INTEGRATION_VERIFICATION.json',dict(status='PASS',fit_attempts=r.ENV['guard']['attempts'],paths=receipts,
          run_replays_sha256=sha(ROOT/'run_replays.py'),engine_cached_sha256=sha(ROOT/'engine_cached.py')))

if __name__=='__main__':main()
