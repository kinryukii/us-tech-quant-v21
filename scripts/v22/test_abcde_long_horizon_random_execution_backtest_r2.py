"""Small offline contract tests for the Phase 2 cache utility; no network and no backtest."""
import importlib.util
from pathlib import Path
import pandas as pd
import tempfile

P=Path(__file__).with_name('abcde_long_horizon_random_execution_backtest_r2.py')
spec=importlib.util.spec_from_file_location('phase2',P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def test_normalize_preserves_raw_qfq_label_and_dates():
    d=pd.DataFrame({'time_key':['2024-01-05','2024-01-08'],'open':[1,2],'high':[2,3],'low':[.5,1.5],'close':[1.5,2.5],'volume':[1,2]})
    r=m.normalize(d,'AAA','qfq','2000-01-01','2024-01-08')
    assert list(r.trade_date)==['2024-01-05','2024-01-08'] and set(r.autype)=={'qfq'}

def test_price_columns_exclude_strategy_outputs():
    assert 'nav' not in m.PRICE_COLUMNS and 'trade' not in m.PRICE_COLUMNS

def test_universe_support_tickers_excluded():
    # Explicit external temp root keeps Phase 2 tests from writing to PROGRAM_ROOT.
    root=Path(r'D:\us-tech-quant-data\moomoo\temp')
    with tempfile.TemporaryDirectory(dir=root) as td:
        tmp_path=Path(td)
        for ticker,support in [('AAA',False),('OLD',True)]:
            d=tmp_path/ticker;d.mkdir();(d/'metadata.json').write_text('{"ticker":"%s","historical_support_ticker":%s}'%(ticker,str(support).lower()))
        assert m.find_universe(tmp_path)==['AAA']
