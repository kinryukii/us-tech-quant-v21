"""Exact-event projection extending the existing pre2026 vendor action reader.

No cash/share amount is inferred from affine factors. Caller freezes the
physical source, request and reader hashes before materialization.
"""
from pathlib import Path
import hashlib
import pandas as pd
import pyarrow.dataset as ds
from scripts.research.a2.factors.economic_return_inputs import read_events

ACTION_COLUMNS = [
 "code","ex_div_date","per_cash_div","special_dividend",
 "split_base","split_ert","join_base","join_ert","split_ratio",
 "bonus_base","bonus_ert","per_share_div_ratio","transfer_base","transfer_ert",
 "per_share_trans_ratio","allot_base","allot_ert","allotment_ratio",
 "allotment_price","add_base","add_ert","stk_spo_ratio","stk_spo_price",
 "spin_off_base","spin_off_ert","spin_off_ratio",
]
def read_exact_vendor_actions(path, expected_sha, keys):
    """Only caller-declared code/date input fields enter pandas."""
    with Path(path).open("rb") as handle:
        if hashlib.file_digest(handle,"sha256").hexdigest()!=expected_sha:
            raise ValueError("VENDOR_ACTION_SOURCE_HASH_CHANGED")
    normalized=[]
    for code,day in keys:
        stamp=pd.Timestamp(day)
        if pd.isna(stamp) or stamp.tzinfo is not None or stamp!=stamp.normalize():
            raise ValueError("INVALID_EXACT_ACTION_DATE")
        normalized.append((str(code),str(stamp.date())))
    keys=normalized
    if not keys or len(keys)!=len(set(keys)):
        raise ValueError("EMPTY_OR_DUPLICATE_EXACT_ACTION_REQUEST")
    if any(not code.strip() or pd.Timestamp(day)<pd.Timestamp("2020-01-01")
           or pd.Timestamp(day)>=pd.Timestamp("2026-01-01") for code,day in keys):
        raise ValueError("VENDOR_ACTION_REQUEST_OUTSIDE_PRE2026")
    exact=None
    for code,day in keys:
        item=(ds.field("code")==code)&(ds.field("ex_div_date")==day)
        exact=item if exact is None else exact|item
    base=ds.dataset(path,format="parquet")
    if not set(ACTION_COLUMNS).issubset(base.schema.names):
        raise ValueError("EXPLICIT_VENDOR_ACTION_SCHEMA_MISSING")
    class ExactProjection:
        def to_table(self, *, filter):
            return base.to_table(columns=ACTION_COLUMNS,filter=filter&exact)
    # Reuse the original predicate/date/code/schema checks, not its old runner.
    frame=read_events(path,{code for code,_ in keys},dataset_factory=lambda *_args,**_kw:ExactProjection())
    observed=set(zip(frame.code.astype(str),frame.ex_div_date.dt.strftime("%Y-%m-%d")))
    if not observed.issubset(keys) or frame.duplicated(["code","ex_div_date"]).any():
        raise ValueError("EXACT_ACTION_PROJECTION_IDENTITY_INVALID")
    return frame

