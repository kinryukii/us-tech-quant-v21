from decimal import Decimal
import json
import pytest

from scripts.storage import refresh_treasury_tic as tic


def source(number=1, periods=('2026-06',), value='-0'):
    columns = ['country', 'country_code', 'date'] + tic.COLUMNS[number]
    rows = ['\t'.join(['Grand Total', '99996', period, value] + ['n.a.'] * (len(columns)-4)) for period in periods]
    return ('\n'.join([f'Table {number}: official fixture', 'Millions of dollars', '\t'.join(columns), *rows, 'Definitions:', 'Source definition'])+'\n').encode()


def test_original_values_null_and_negative_zero():
    rows, metadata = tic.parse_tsv(source(), 1, '2026-09-15')
    frame = tic.normalize(rows, {'retrieval_timestamp_utc':'2026-09-14T17:00:00Z','source_reference':tic.URLS['table1'],'sha256':'a'*64})
    record = frame.to_pylist()[0]
    assert record['date']=='2026-06-01' and record['source_period']=='2026-06' and record['period_end']=='2026-06-30'
    assert record['for_lt_total_pos']=='-0' and record['for_lt_total_pos_value']==Decimal(0)
    assert record['for_lt_total_net']=='n.a.' and record['for_lt_total_net_value'] is None
    assert record['available_at_utc'] is None and not record['historical_pit_certified']
    assert json.loads(record['source_record_json'])['date']=='2026-06'
    assert metadata['footer_lines']==['Definitions:', 'Source definition']


@pytest.mark.parametrize('value', ['NaN', '', '1.5', '1,000', '<1', 's', '1e6'])
def test_unknown_numeric_tokens_stop(value):
    with pytest.raises(ValueError, match='UNKNOWN_VALUE_TOKEN'):
        tic.parse_tsv(source(value=value), 1, '2026-09-15')


@pytest.mark.parametrize('periods,number,reason', [
    (('2026-06','2026-06'),1,'DUPLICATE'),
    (('2026-06','2026-04'),1,'INTERNAL_SOURCE_MONTH_GAP'),
    (('2026-10',),1,'OUT_OF_SCOPE'),
    (('2023-01',),4,'OUT_OF_SCOPE'),
    (('2019-12',),1,'OUT_OF_SCOPE'),
])
def test_invalid_calendar_coverage(periods,number,reason):
    with pytest.raises(ValueError, match=reason):
        tic.parse_tsv(source(number, periods), number, '2026-09-15')


@pytest.mark.parametrize('old,new,reason', [
    (b'Millions of dollars',b'Billions of dollars','UNIT'),
    (b'for_lt_total_pos',b'unknown_field','SCHEMA'),
    (b'Definitions:',b'broken footer','FOOTER'),
    (b'99996',b'12345','GRAND_TOTAL'),
])
def test_schema_and_truncation_fail_closed(old,new,reason):
    with pytest.raises(ValueError, match=reason):
        tic.parse_tsv(source().replace(old,new),1,'2026-09-15')


def test_html_independent_format_comparison():
    rows, _ = tic.parse_tsv(source(4),4,'2026-09-15')
    html = '<table><tr>'+''.join('<td><span>'+v+'</span></td>' for v in rows[0][1].values())+'</tr></table>'
    result=tic.verify_html(html.encode(),4,rows)
    assert result['records_compared']==1 and result['cells_compared']==21
    with pytest.raises(ValueError,match='HTML_TSV_ROWS_DIFFER'):
        tic.verify_html(html.replace('-0','1').encode(),4,rows)
    layout_html=html.replace('</tr>','<td>&nbsp;</td></tr>')
    assert tic.verify_html(layout_html.encode(),4,rows)['blank_html_layout_cells_ignored']==1
    with pytest.raises(ValueError,match='HTML_TSV_ROWS_DIFFER'):
        tic.verify_html(layout_html.replace('&nbsp;','extra').encode(),4,rows)


def test_same_labels_different_source_entity_codes_preserved():
    body=source().replace(b'Grand Total\t99996\t2026-06\t-0',b'Grand Total\t99996\t2026-06\t-0')
    lines=body.decode().splitlines()
    lines.insert(4,lines[3].replace('99996','81655'))
    rows, metadata=tic.parse_tsv(('\n'.join(lines)).encode(),1,'2026-09-15')
    assert len(rows)==2 and len(metadata['coverage'])==2
