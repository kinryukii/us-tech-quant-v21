from pathlib import Path
import sys, math
sys.path.insert(0,str(Path(__file__).parents[1]/'storage'))
from abcde_signal_store import load_ticker_qfq,compute_forward_returns_from_qfq
def test_forward_uses_trading_rows():
 f,_=load_ticker_qfq('AMD'); d=f.date.iloc[0]; x=compute_forward_returns_from_qfq('AMD',[d]); assert abs(x.forward_1d.iloc[0]-(f.close.iloc[1]/f.close.iloc[0]-1))<1e-14; assert math.isnan(compute_forward_returns_from_qfq('AMD',[f.date.iloc[-1]]).forward_1d.iloc[0])
