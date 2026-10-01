"""Reuse only immutable input parsing; account transition code is unchanged.

The frozen reference function is compiled with one optional prepared-input
branch. Cash, units, marks, orders, fills and every account transition remain
the original code and are freshly initialized on each invocation. The tests
compare every ledger with the unmodified reference, including missing quotes.
"""
from __future__ import annotations
import inspect
import pandas as pd
import numpy as np
import engine_v2 as reference

class PreparedInputs:
    def __init__(self,prices,calendar,features):
        self.original_prices=prices;self.original_features=features
        self.calendar=reference.dates(calendar,'calendar')
        for frame,required,name in [(prices,{'ticker','trade_date','open','close'},'prices'),
             (features,{'ticker','signal_date'},'features')]:
            if not required.issubset(frame): raise ValueError(name+' missing columns')
            if not frame.ticker.map(lambda t:isinstance(t,str) and bool(t.strip())).all():raise ValueError(name+' invalid ticker')
        self.px=prices.copy();self.fs=features.copy()
        self.px['trade_date']=reference.dates(self.px.trade_date,'trade_date')
        self.fs['signal_date']=reference.dates(self.fs.signal_date,'signal_date')
        if self.px.duplicated(['trade_date','ticker']).any() or self.fs.duplicated(['signal_date','ticker']).any():raise ValueError('duplicate key')
        if not self.fs.signal_date.isin(self.calendar).all():raise ValueError('signal outside calendar')
        if 'price_quality_warning' not in self.px:self.px['price_quality_warning']=False
        else:self.px['price_quality_warning']=self.px.price_quality_warning.fillna(True).astype(bool)
        for c in ['open','close']:self.px[c]=pd.to_numeric(self.px[c],errors='coerce')
        self.quotes={d:{r.ticker:(r.open,r.close,bool(r.price_quality_warning)) for r in g.itertuples()}
             for d,g in self.px.loc[self.px.trade_date.isin(self.calendar)].groupby('trade_date',sort=False)}
        self.frames={d:g.copy() for d,g in self.fs.groupby('signal_date',sort=False)}
        self.signal_advs={};self.adv_histories={};self.input_names={};self.bad_close_inputs={};last_adv={}
        for d in self.calendar:
            day=self.frames.get(d,self.fs.iloc[:0])
            adv=dict(zip(day.ticker,day.avg_dollar_volume_20d)) if 'avg_dollar_volume_20d' in day else {}
            self.signal_advs[d]=adv
            for ticker,value in adv.items():
                if reference.positive(value):last_adv[ticker]=(float(value),d)
            self.adv_histories[d]=last_adv.copy()
            names=set(day.ticker);self.input_names[d]=names
            q=self.quotes.get(d,{})
            self.bad_close_inputs[d]={t for t in names if t not in q or q[t][2] or not reference.positive(q[t][1])}
    def checked(self,prices,calendar,features):
        if prices is not self.original_prices or features is not self.original_features or not self.calendar.equals(pd.DatetimeIndex(calendar)):
            raise ValueError('PREPARED_INPUT_IDENTITY_MISMATCH')
        return self.px,self.fs,self.quotes,self.frames

def _compile_cached_reference():
    source=inspect.getsource(reference.run_replay)
    old='    missing_signal_policy="hold",\n'
    assert source.count(old)==1
    source=source.replace(old,'    missing_signal_policy="hold", prepared_inputs=None,\n')
    first=source.index('    for frame, required, name in [(prices,')
    last=source.index('    lo = pd.Timestamp(signal_start)',first)
    block=source[first:last]
    wrapped='    if prepared_inputs is None:\n'+''.join('    '+line if line.strip() else line for line in block.splitlines(keepends=True))
    wrapped+='    else:\n        px, fs, quotes, frames = prepared_inputs.checked(prices, cal, features)\n'
    source=source[:first]+wrapped+source[last:]
    start=source.index('        signal_adv = dict(zip(source_day.ticker, source_day[adv_column]))')
    end=source.index('\n        def quote(',start)
    block=source[start:end]
    wrapped='        if prepared_inputs is None or adv_column != "avg_dollar_volume_20d":\n'+''.join('    '+line if line.strip() else line for line in block.splitlines(keepends=True))
    wrapped+='\n        else:\n            signal_adv = prepared_inputs.signal_advs[date]\n            last_adv = prepared_inputs.adv_histories[date]\n'
    source=source[:start]+wrapped+source[end:]
    source=source.replace('            input_names = set(source_day.ticker)',
       '            input_names = set(source_day.ticker) if prepared_inputs is None else prepared_inputs.input_names[date]')
    source=source.replace('            for ticker in set(holdings) | input_names:',
       '            for ticker in set(holdings) | (input_names if prepared_inputs is None else prepared_inputs.bad_close_inputs[date]):')
    namespace=reference.__dict__.copy()
    exec(compile(source,__file__,'exec'),namespace)
    return namespace['run_replay']

run_replay=_compile_cached_reference()
