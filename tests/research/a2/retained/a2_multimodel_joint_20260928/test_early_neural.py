"""The extra MLP fold must fit only 2023, before its 2024 OOF predictions."""
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import early_neural_train as early


def panel(signal='2023-12-27',end='2023-12-29',available=True):
    return pd.DataFrame([dict(signal_date=pd.Timestamp(signal),label_end_date=pd.Timestamp(end),
                              label_available=available)])


def test_reader_requests_both_signal_and_label_2023_filters(monkeypatch):
    calls=[]
    def read(source,filters):calls.append(filters);return panel()
    monkeypatch.setattr(early.pd,'read_parquet',read)
    actual=early.load_early_panel('synthetic')
    boundary=pd.Timestamp('2023-12-31')
    assert calls==[[('signal_date','<=',boundary),('label_end_date','<=',boundary)]]
    assert len(actual)==1


@pytest.mark.parametrize('signal,end',[
    ('2024-01-02','2024-01-04'),('2023-12-29','2024-01-03')])
def test_reader_defensively_rejects_any_2024_signal_or_label(monkeypatch,signal,end):
    monkeypatch.setattr(early.pd,'read_parquet',lambda *args,**kwargs:panel(signal,end))
    with pytest.raises(RuntimeError,match='OUTSIDE_2023'):early.load_early_panel('synthetic')


def test_reader_rejects_unavailable_labels(monkeypatch):
    monkeypatch.setattr(early.pd,'read_parquet',lambda *args,**kwargs:panel(available=False))
    with pytest.raises(RuntimeError,match='NOT_AVAILABLE'):early.load_early_panel('synthetic')
