from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import urllib.error
import json
import pytest
from scripts.storage import refresh_cftc_bpr as m


def sample(*,count_us='',count_non='',month='9/1/2026',market='CBT UST BOND',long_total='30',single=False):
    header='<tr><td></td><td colspan="7">REPORT DATE: '+month+'</td></tr><tr>'+''.join('<td>'+h+'</td>' for h in m.HEADERS)+'</tr>'
    us='<tr><td rowspan="3">'+market+'</td><td>U.S.</td><td>'+count_us+'</td><td>10</td><td>10.0</td><td>12</td><td>12.0</td><td>100</td></tr>'
    non='<tr><td>NON U.S.</td><td>'+count_non+'</td><td>20</td><td>20.0</td><td>14</td><td>14.0</td><td>&nbsp;</td></tr>'
    total='<tr><td> </td><td>8</td><td>'+long_total+'</td><td>30.0</td><td>26</td><td>26.0</td><td></td></tr>'
    if single:
        us='';non='<tr><td rowspan="2">'+market+'</td><td>NON U.S.</td><td></td><td>30</td><td>30.0</td><td>26</td><td>26.0</td><td>100</td></tr>'
    return ('<html><table>'+header+us+non+total+'</table></html>').encode()


def test_rowspan_raw_blank_and_group_open_interest():
    rows,qc=m.parse_report(sample(),'2026-09','2026-09-15')
    assert len(rows)==3 and [r['bank_category'] for r in rows]==['US','NON_US','TOTAL']
    assert all(r['bank_count'] is None for r in rows[:2])
    assert rows[2]['bank_count']==Decimal(8)
    assert rows[1]['open_interest'] is None and rows[1]['open_interest_text']=='\xa0'
    assert all(r['market_open_interest']==Decimal(100) for r in rows)
    assert json.loads(rows[2]['source_cells_json'])[0]['source_row']==3
    assert all(r['available_at_utc'] is None and not r['historical_pit_certified'] for r in rows)
    assert qc['report_date']=='2026-09-01'


def test_missing_category_not_fabricated():
    rows,_=m.parse_report(sample(single=True),'2026-09','2026-09-15')
    assert [r['bank_category'] for r in rows]==['NON_US','TOTAL']


def test_source_suppression_mark_kept():
    rows,_=m.parse_report(sample(count_us='*',count_non='*'),'2026-09','2026-09-15')
    assert rows[0]['bank_count_text']=='*' and rows[0]['bank_count'] is None and rows[0]['bank_count_status']=='SOURCE_TOKEN'


@pytest.mark.parametrize('raw,error',[
    (sample(long_total='31'),'POSITION_TOTAL'),
    (sample(count_us='4',count_non='5'),'COUNT_TOTAL'),
    (sample(month='9/16/2026'),'DATE_SCOPE'),
    (sample(month='8/4/2026'),'DATE_SCOPE'),
    (sample(market='UNSELECTED'),'EMPTY_FINANCIAL'),
    (sample().replace(b'NON U.S.',b'UNKNOWN'),'UNKNOWN_BANK'),
    (sample().replace(b'rowspan="3"',b'rowspan="4"'),'WIDTH|PAST_TABLE'),
    (sample().replace(b'<td>30.0</td>',b''),'WIDTH'),
    (sample().replace(b'LONG FUTURES',b'LONG CALLS'),'TABLE_NOT_UNIQUE'),
])
def test_fail_closed_bad_source(raw,error):
    with pytest.raises(ValueError,match=error):m.parse_report(raw,'2026-09','2026-09-15')


def test_number_preserves_exact_and_unknown():
    assert m.number('12,345,678')==Decimal('12345678')
    assert m.number('12.5',False)==Decimal('12.5')
    assert m.number('12,34') is None
    assert m.number('--') is None


def test_nested_table_rejected():
    with pytest.raises(ValueError,match='NESTED'):m.document(b'<table><tr><td><table></table></td></tr></table>')


def index_html():
    reverse={v:k for k,v in m.MONTHS.items()};parts=[]
    for n in range(2024*12+8,2026*12+9):
        year,zero_month=divmod(n,12)
        parts.append('<a href="/MarketReports/BankParticipation/dea'+reverse[zero_month+1]+str(year)[2:]+'f">Futures</a>')
    return ''.join(parts).encode()


def test_complete_official_link_scope_and_no_options():
    tasks=m.linked_reports(index_html()+b'<a href="/MarketReports/BankParticipation/deasep26o">Options</a>','2026-09-15')
    assert len(tasks)==25 and tasks[0]['month']=='2024-09' and tasks[-1]['month']=='2026-09'


def test_official_index_missing_month_and_cross_host():
    raw=index_html()
    with pytest.raises(ValueError,match='25_MONTH'):m.linked_reports(raw.replace(b'deasep24f',b'other'),'2026-09-15')
    with pytest.raises(ValueError,match='UNEXPECTED_REPORT_LINK'):m.linked_reports(raw.replace(b'/MarketReports/BankParticipation/deasep24f',b'https://evil.example/MarketReports/BankParticipation/deasep24f'),'2026-09-15')


def test_latest_comparison_keeps_source_tokens_and_ignores_layout():
    rows,_=m.parse_report(sample(),'2026-09','2026-09-15')
    changed=[{**r,'source_table_row':r['source_table_row']+1,'source_cells_json':'different layout'} for r in rows]
    assert m.normalized_signature(rows)==m.normalized_signature(changed)
    changed[0]['long_futures_text']='010'
    assert m.normalized_signature(rows)!=m.normalized_signature(changed)


@pytest.mark.parametrize('status',[403,429,503])
def test_http_failure_stops_and_cannot_repeat(tmp_path,monkeypatch,status):
    paths=SimpleNamespace(results_root=tmp_path/'results',cache_root=tmp_path/'cache',repo_root=Path('D:/us-tech-quant'))
    calls=[]
    def denied(request,timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url,status,'synthetic',{},None)
    monkeypatch.setattr(m.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=denied))
    monkeypatch.setattr(m.time,'sleep',lambda seconds:None)
    monkeypatch.setattr(m,'disk_floor',lambda *a:None)
    with pytest.raises(ValueError,match='FAILED_NO_RETRY'):m.fetch(paths,'synthetic','index',m.INDEX,{m.INDEX})
    for name in ['index','another']:
        with pytest.raises((ValueError,TypeError)):m.fetch(paths,'synthetic',name,m.INDEX,{m.INDEX})
    assert calls==[m.INDEX]


def test_cached_raw_zero_get_and_hash_change_rejected(tmp_path,monkeypatch):
    paths=SimpleNamespace(results_root=tmp_path/'results',cache_root=tmp_path/'cache',repo_root=Path('D:/us-tech-quant'))
    calls=[]
    class Response:
        status=200;url=m.INDEX;headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return b'<html>official fixture</html>'
    def request(req,timeout):calls.append(req.full_url);return Response()
    monkeypatch.setattr(m.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=request))
    monkeypatch.setattr(m.time,'sleep',lambda seconds:None);monkeypatch.setattr(m,'disk_floor',lambda *a:None)
    first=m.fetch(paths,'synthetic','index',m.INDEX,{m.INDEX})
    assert m.fetch(paths,'synthetic','index',m.INDEX,{m.INDEX})==first and len(calls)==1
    Path(first['raw']['local_path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='HASH_IDENTITY'):m.fetch(paths,'synthetic','index',m.INDEX,{m.INDEX})
    assert len(calls)==1
