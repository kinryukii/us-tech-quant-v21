"""Source integrity tests using synthetic G.17 fixtures only."""
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from decimal import Decimal
import io
import json
import zipfile

import pytest
import pyarrow as pa

from scripts.storage import refresh_frb_g17 as mod


def text_row(code='GMF',year=1990,values=('1.0000',)):
    return ('"'+code+'"').ljust(16)+str(year)+'   '+''.join(x.rjust(10) for x in values)


def text_fixture(values=('1.0000',),code='GMF',description='Manufacturing (NAICS)'):
    return ('"'+code+': '+description+'"\n'+text_row(code,values=values)+'\n').encode()


def structure():
    codes={'CL_FREQ':{'129':'Monthly'},'CL_SA':{'SA':'Seasonally adjusted'},
        'CL_UNIT':{'Index:_2017_100':'Index: 2017 = 100','Percentage':'Percentage'},
        'CL_UNIT_MULT':{'1':'One'},'CL_OBS_STATUS':{'A':'Normal','ND':'No data'}}
    lists=''.join('<s:CodeList id="'+cl+'" agency="FRB">'+''.join('<s:Code value="'+code+'"><s:Description>'+label+'</s:Description></s:Code>' for code,label in items.items())+'</s:CodeList>' for cl,items in codes.items())
    return ('<m:Structure xmlns:m="'+mod.NS['m']+'" xmlns:s="'+mod.NS['s']+'"><m:CodeLists>'+lists+'</m:CodeLists></m:Structure>').encode()


def series(dataset='IP_MAJOR_INDUSTRY_GROUPS',value='1.0000',period='1990-01-31',status='A',attrs=''):
    return ('<f:DataSet id="'+dataset+'" xmlns:k="http://www.federalreserve.gov/structure/compact/G17_'+dataset+'">'
        '<k:Series CURRENCY="NA" FREQ="129" SA="SA" SERIES_CODE="GMF" SERIES_NAME="IP.GMF.S" UNIT="Index:_2017_100" UNIT_MULT="1" '+attrs+'>'
        '<f:Annotations><c:Annotation><c:AnnotationType>Long Description</c:AnnotationType><c:AnnotationText>Current classification; old revision</c:AnnotationText></c:Annotation></f:Annotations>'
        '<f:Obs OBS_STATUS="'+status+'" OBS_VALUE="'+value+'" TIME_PERIOD="'+period+'" />'
        '</k:Series></f:DataSet>')


def xml_data(body=None):
    body=series() if body is None else body
    return ('<m:MessageGroup xmlns:m="'+mod.NS['m']+'" xmlns:f="'+mod.NS['f']+'" xmlns:c="'+mod.NS['c']+'">'
        '<m:Header><m:ID>G17</m:ID><m:Test>false</m:Test><m:Prepared>2026-08-14T19:03:47</m:Prepared></m:Header>'+body+'</m:MessageGroup>').encode()


def zipped(data=None,struct=None,extra=None):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('G17_data.xml',xml_data() if data is None else data)
        archive.writestr('G17_struct.xml',structure() if struct is None else struct)
        if extra:archive.writestr(*extra)
    return output.getvalue()


def parse(payload):
    return mod.parse_sdmx(payload,{'release_date':'2026-08-18'},{'IP.GMF.S':'IP_MAJOR_INDUSTRY_GROUPS'})


def test_text_preserves_fixed_width_positions_original_and_naics():
    rows,desc=mod.parse_text(text_fixture(('1.0000','2.1234'),'G333','Machinery  NAICS=333'),'IP','1990-02',('G333',))
    row=rows[('IP.G333.S','1990-02-28')]
    assert row['value']==Decimal('2.1234') and row['provider_value_text']=='2.1234'
    assert row['source_text_cell']=='    2.1234' and row['source_month_slot']==2 and row['source_text_line_number']==2
    assert desc['G333']['naics_current']=='333'


def test_text_blank_month_cannot_shift_later_values_left():
    with pytest.raises(ValueError,match='INTERNAL_EMPTY_MONTH'):
        mod.parse_text(text_fixture(('1.0000','','3.0000')),'IP','1990-03',('GMF',))


def test_text_future_trailing_blank_allowed_but_data_refused():
    rows,_=mod.parse_text(text_fixture(),'IP','1990-01',('GMF',));assert len(rows)==1
    with pytest.raises(ValueError,match='FUTURE_MONTH'):
        mod.parse_text(text_fixture(('1.0000','2.0000')),'IP','1990-01',('GMF',))


def test_text_duplicate_year_and_header_identity_rejected():
    raw=text_fixture()+ (text_row()+'\n').encode()
    with pytest.raises(ValueError,match='DUPLICATE_TEXT_YEAR'):mod.parse_text(raw,'IP','1990-01',('GMF',))
    with pytest.raises(ValueError,match='MATCHING_DESCRIPTION'):
        mod.parse_text(text_fixture().replace(b'"GMF"',b'"G333"'),'IP','1990-01',('GMF',))


def test_unselected_official_code_with_at_sign_is_not_misparsed():
    raw=text_fixture()+text_fixture(code='G325@4',description='Chemicals except medicines')
    rows,_=mod.parse_text(raw,'IP','1990-01',('GMF',));assert len(rows)==1


def test_sdmx_preserves_original_status_attributes_annotations_and_generation_time():
    rows,meta=parse(zipped());row=rows[('IP.GMF.S','1990-01-31')]
    assert row['value']==Decimal('1.0000') and row['provider_unit_mult']=='1'
    assert row['source_observation_ordinal']==1 and row['provider_observation_status']=='A'
    assert json.loads(row['source_observation_attributes_json'])['OBS_VALUE']=='1.0000'
    assert 'old revision' in meta['series']['IP.GMF.S']['primary']['series_annotations_xml'][0]
    assert meta['header']['prepared_timestamp_text']=='2026-08-14T19:03:47'


def test_identical_presentation_copies_explicitly_preserved():
    body=series()+series('IP_DURABLE_GOODS_DETAIL')
    rows,meta=parse(zipped(xml_data(body)))
    assert len(rows)==1 and len(meta['series']['IP.GMF.S']['published_copies'])==2


def test_presentation_copy_value_or_annotation_conflict_refused():
    with pytest.raises(ValueError,match='PUBLISHED_SERIES_CONFLICT'):
        parse(zipped(xml_data(series()+series('IP_DURABLE_GOODS_DETAIL','1.0001'))))
    with pytest.raises(ValueError,match='PUBLISHED_SERIES_CONFLICT'):
        parse(zipped(xml_data(series()+series('IP_DURABLE_GOODS_DETAIL').replace('old revision','different revision'))))


def test_missing_sentinel_remains_null():
    rows,_=parse(zipped(xml_data(series(value='-9999',status='ND'))))
    row=next(iter(rows.values()));assert row['value'] is None and row['provider_value_text']=='-9999' and row['provider_status_label']=='No data'


@pytest.mark.parametrize('change,message',[
    (lambda x:x.replace(b'Index:_2017_100',b'Index:_2022_100'),'ATTRIBUTES_CHANGED'),
    (lambda x:x.replace(b'SA="SA"',b'SA="NSA"'),'ATTRIBUTES_CHANGED'),
    (lambda x:x.replace(b'UNIT_MULT="1"',b'UNIT_MULT="1000"'),'ATTRIBUTES_CHANGED'),
    (lambda x:x.replace(b'TIME_PERIOD="1990-01-31"',b'TIME_PERIOD="1990-01-01"'),'NOT_MONTH_END'),
    (lambda x:x.replace(b'OBS_VALUE="1.0000"',b'OBS_VALUE="NaN"'),'VALUE_OR_STATUS'),
    (lambda x:x.replace(b'OBS_STATUS="A"',b'OBS_STATUS="X"'),'VALUE_OR_STATUS'),
    (lambda x:x.replace(b'<m:ID>G17</m:ID>',b'<m:ID>H10</m:ID>'),'HEADER_IDENTITY'),
    (lambda x:x.replace(b'</m:MessageGroup>',b'<m:Footer>Partial</m:Footer></m:MessageGroup>'),'PROVIDER_ERROR_OR_FOOTER'),
    (lambda x:b'<!DOCTYPE x [<!ENTITY y "x">]>'+x,'EXTERNAL_DECLARATION'),
])
def test_sdmx_contract_changes_fail_closed(change,message):
    with pytest.raises(ValueError,match=message):parse(zipped(change(xml_data())))


def test_nonprimary_only_and_zip_path_traversal_refused():
    with pytest.raises(ValueError,match='PRIMARY_SET_INCOMPLETE'):
        parse(zipped(xml_data(series('IP_DURABLE_GOODS_DETAIL'))))
    with pytest.raises(ValueError,match='UNSAFE_ZIP_MEMBER'):parse(zipped(extra=('../bad.txt','bad')))


def test_decimal_storage_and_missing_never_float():
    values=[mod.number('123456789012.1234'),mod.number('-9999','ND')]
    assert pa.array(values,pa.decimal128(20,4)).to_pylist()==values
    with pytest.raises(ValueError,match='MISSING_SENTINEL'):mod.number('0.0000','ND')
    with pytest.raises(ValueError,match='NONPOSITIVE'):mod.number('0.0000')


def test_month_end_leap_year_and_release_boundary():
    assert mod.month_end('2024-02')=='2024-02-29'
    raw=b'Industrial Production and Capacity Utilization Release Date: August 18, 2026 2017=100'
    assert mod.parse_release(raw,'2026-09-15')['release_date']=='2026-08-18'
    with pytest.raises(ValueError,match='RELEASE_AFTER_AS_OF'):mod.parse_release(raw,'2026-08-17')
    with pytest.raises(ValueError,match='BASE_YEAR_CHANGED'):mod.parse_release(raw.replace(b'2017=100',b'2022=100'),'2026-09-15')


def test_access_denial_stops_without_retry(tmp_path,monkeypatch):
    @dataclass
    class Raw:
        status:str='FAILED'
        local_path:str=''
    class Archive:
        def acquire_url(self,url,*args):
            try:self._download_once(url,60)
            except ValueError:return Raw()
    class Response:
        status_code=429;headers={}
        def __enter__(self):return self
        def __exit__(self,*args):return False
    calls=[]
    monkeypatch.setattr(mod.requests,'get',lambda *a,**k:(calls.append(a),Response())[1])
    monkeypatch.setattr(mod.common,'archive_module',lambda _:Archive());monkeypatch.setattr(mod.time,'sleep',lambda _:None)
    monkeypatch.setattr(mod.shutil,'disk_usage',lambda _:SimpleNamespace(free=100*1024**3))
    paths=SimpleNamespace(repo_root=tmp_path,cache_root=tmp_path/'cache',data_root=tmp_path/'data',results_root=tmp_path/'results')
    paths.cache_root.mkdir();paths.data_root.mkdir()
    with pytest.raises(ValueError,match='ACQUISITION_FAILED'):mod.fetch(paths,'test','first','https://www.federalreserve.gov/first')
    with pytest.raises(ValueError,match='PRIOR_ACCESS_DENIAL'):mod.fetch(paths,'test','second','https://www.federalreserve.gov/second')
    assert len(calls)==1
