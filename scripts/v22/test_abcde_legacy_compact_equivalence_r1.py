from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'storage'))
from abcde_signal_store import load_compact_rank_history
def test_top20_per_strategy_date_is_unique():
 f=load_compact_rank_history(); assert not f.duplicated(['research_date','strategy_id','ticker']).any(); sizes=f.groupby(['research_date','strategy_id']).size(); assert sizes.groupby(level=0).nunique().eq(1).all(); assert set(sizes.unique())=={315,325}
