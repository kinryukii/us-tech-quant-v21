from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'storage'))
from abcde_signal_store import load_compact_rank_history
def test_compact_history_contract():
 f=load_compact_rank_history(); assert len(f)==4825; assert f.research_date.nunique()==3; assert f.strategy_id.nunique()==5
