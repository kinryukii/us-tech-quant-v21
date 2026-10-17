"""Exact pre2026 official H10 edition -> CAD row; no network or account replay."""
from dataclasses import asdict
from datetime import datetime
from html.parser import HTMLParser
import hashlib
import math
from pathlib import Path
import re
import pandas as pd
from scripts.v22.corporate_action_transition_r1 import SourceBackedFXMark, CAD_PER_USD

MAX_EDITION_BYTES = 1024 * 1024


class _Cells(HTMLParser):
    def __init__(self):
        super().__init__(); self.cells=[]; self._capture=None; self._text=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("th","td"):
            self._capture=tag;self._text=[]
    def handle_data(self,data):
        if self._capture is not None:self._text.append(data)
    def handle_endtag(self,tag):
        if tag==self._capture:
            self.cells.append(" ".join("".join(self._text).split()));self._capture=None


def parse_cad_h10_release(path, *, expected_sha256, expected_release_date):
    path=Path(path)
    if (path.suffix.lower() != ".html" or path.stat().st_size > MAX_EDITION_BYTES
            or not re.fullmatch(r"[0-9a-f]{64}",str(expected_sha256))):
        raise ValueError("BOUNDED_PHYSICALLY_PINNED_H10_EDITION_REQUIRED")
    release=pd.Timestamp(expected_release_date)
    if (release.tzinfo is not None or release != release.normalize()
            or not pd.Timestamp("2023-01-01") <= release < pd.Timestamp("2026-01-01")):
        raise ValueError("PRE2026_EXACT_RELEASE_DATE_REQUIRED")
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:
        raise ValueError("H10_EDITION_SOURCE_CHANGED")
    # Qualify official edition date and its conservative available bound before
    # decoding any rate cells. Raw footer/current navigation are never projected.
    match=re.search(rb'<div[^>]*class=[\"\']dates[\"\'][^>]*>\s*Release Date:\s*([^<]+)',raw,re.I)
    if match is None:
        raise ValueError("OFFICIAL_H10_EDITION_HEADER_REQUIRED")
    official=pd.Timestamp(datetime.strptime(match.group(1).decode("ascii").strip(),"%B %d, %Y"))
    if official!=release:
        raise ValueError("H10_SOURCE_RELEASE_DATE_MISMATCH")
    available=(release+pd.Timedelta(hours=23,minutes=59,seconds=59)).tz_localize("America/New_York").tz_convert("UTC")
    if available>=pd.Timestamp("2026-01-01",tz="UTC"):
        raise ValueError("H10_AVAILABILITY_BOUND_AFTER_PRE2026_SCOPE")
    unit=re.search(rb'<div[^>]*class=[\"\']tableunit[\"\'][^>]*>(.*?)</div>',raw,re.I|re.S)
    if unit is None or b'currency units per U.S. dollar' not in unit.group(1):
        raise ValueError("H10_CURRENCY_PER_USD_SOURCE_UNIT_REQUIRED")
    head=re.search(rb'<thead[^>]*>(.*?)</thead>',raw,re.I|re.S)
    if head is None:raise ValueError("H10_OBSERVATION_COLUMN_HEADER_REQUIRED")
    parser=_Cells();parser.feed(head.group(1).decode("utf-8"));labels=parser.cells
    if len(labels)!=7 or labels[:2]!=["COUNTRY","CURRENCY"]:
        raise ValueError("H10_EXACT_FIVE_OBSERVATION_HEADER_REQUIRED")
    observations=[]
    for label in labels[2:]:
        normalized=label.replace(".","")
        candidates=[]
        for year in (release.year-1,release.year):
            try:d=pd.Timestamp(datetime.strptime(normalized+" "+str(year),"%b %d %Y"))
            except ValueError:continue
            if d<=release and d>=release-pd.Timedelta(days=14):candidates.append(d)
        if len(candidates)!=1 or candidates[0]>=pd.Timestamp("2026-01-01"):
            raise ValueError("H10_CAUSAL_PRE2026_OBSERVATION_DATE_REQUIRED")
        observations.append(candidates[0])
    rows=list(re.finditer(rb'<tr[^>]*>\s*<th[^>]*>\s*CANADA\s*</th>(.*?)</tr>',raw,re.I|re.S))
    if len(rows)!=1:raise ValueError("H10_UNIQUE_EXACT_NONASTERISK_CANADA_ROW_REQUIRED")
    parser=_Cells();parser.feed(rows[0].group(0).decode("utf-8"));cells=parser.cells
    if len(cells)!=7 or cells[:2]!=["CANADA","DOLLAR"]:
        raise ValueError("H10_CAD_EXACT_ROW_COORDINATE_REQUIRED")
    marks=[];missing=[]
    for day,value in zip(observations,cells[2:]):
        if value=="ND":missing.append(str(day.date()));continue
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",value):
            raise ValueError("H10_EXPLICIT_FINITE_CAD_RATE_REQUIRED")
        rate=float(value)
        marks.append(SourceBackedFXMark("CAD",CAD_PER_USD,str(day.date()),str(available),rate,str(path),expected_sha256))
    return dict(schema="CONSENSUS_PRE2026_H10_CAD_EDITION_SOURCE_FACTS_R1",release_date=str(release.date()),
        available_at=str(available),actual_publication_timestamp="UNKNOWN_RETAINED",
        availability_clock="SOURCE_RELEASE_DATE_END_NY_CONSERVATIVE_BOUND_NOT_ACTUAL_TIME",
        source_date_basis="OFFICIAL_EDITION_HEADER",source_ref={"path":str(path),"sha256":expected_sha256},
        quote_unit=CAD_PER_USD,usd_per_cad_rule="1 / source CAD_PER_USD",observations=[asdict(m) for m in marks],
        no_data_observation_dates=missing,other_currency_values_decoded=False,
        actual_broker_fx_payment_or_tax_certified=False,strict_PIT_certified=False)
