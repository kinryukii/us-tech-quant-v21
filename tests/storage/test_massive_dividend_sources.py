import json,pytest
from scripts.storage import massive_dividend_sources as M
def body(rows):return json.dumps({'status':'OK','results':rows}).encode()
def row(day='2025-06-18',**extra):return dict(ticker='LRCX',ex_dividend_date=day,declaration_date='2025-05-21',cash_amount=.23,currency='USD',distribution_type='recurring',split_adjusted_cash_amount=999,historical_adjustment_factor=999,**extra)
def test_window_selects_exact_targets_and_never_adjustment_fields():
 out=M.project_dividends(body([row('2025-03-19'),row()]),ticker='LRCX',start_date='2025-01-01',end_date='2025-12-31',target_dates=['2025-06-18']);assert len(out['records'])==1 and out['records'][0]['cash_amount']==.23;assert not any(k in out['records'][0] for k in M.EXCLUDED);assert out['outside_exact_target_numeric_rows_decoded']==0
@pytest.mark.parametrize('bad',[dict(ticker='OTHER',ex_dividend_date='2025-06-18',cash_amount=123),dict(ticker='LRCX',ex_dividend_date='2026-06-18',cash_amount=123)])
def test_any_response_identity_or_future_date_rejects_before_cash(bad):
 with pytest.raises(ValueError,match='NO_NUMERIC_DECODE'):M.project_dividends(body([row(),bad]),ticker='LRCX',start_date='2025-01-01',end_date='2025-12-31',target_dates=['2025-06-18'])
def test_post2025_declaration_rejected_without_cash_decode():
 r=row();r['declaration_date']='2026-01-03';out=M.project_dividends(body([r]),ticker='LRCX',start_date='2025-01-01',end_date='2025-12-31',target_dates=['2025-06-18']);assert out['records']==[] and out['rejected_target_metadata'][0]['reason']=='DECLARATION_NOT_PRE2026_NO_CASH_DECODE'
def test_multiple_same_day_components_retained_without_sum_or_choice():
 regular=row();special=row();special.update(cash_amount=.66,distribution_type='special');out=M.project_dividends(body([regular,special]),ticker='LRCX',start_date='2025-01-01',end_date='2025-12-31',target_dates=['2025-06-18']);assert out['records']==[ {k:v for k,v in x.items() if k in M.FIELDS} for x in (regular,special)] and not out['native_qualified']
def test_next_page_original_resource_and_secret_removal():
 out=M.safe_next_url('https://api.massive.com/stocks/v1/dividends?cursor=abc&apiKey=secret&access_token=secret');assert out.endswith('cursor=abc') and 'secret' not in out
 with pytest.raises(ValueError):M.safe_next_url('https://other.example/stocks/v1/dividends?cursor=abc')
