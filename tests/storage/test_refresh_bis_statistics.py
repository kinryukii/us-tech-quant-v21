"""Synthetic contract checks; no network, credentials, or investment research."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import json

import pytest
import pyarrow as pa

from scripts.storage import refresh_bis_statistics as mod


def structure(kind):
    fields={k:None for k in mod.CONFIG[kind]['dimensions']+['TIME_PERIOD',
        'TIME_FORMAT','OBS_PRE_BREAK','COMPILATION','SOURCE_REF','SUPP_INFO_BREAKS','TITLE','TITLE_TS','DECIMALS']}
    fields.update(FREQ='freq',REF_AREA='area',UNIT_MEASURE='unit',UNIT_MULT='mult',
        OBS_STATUS='status',OBS_CONF='conf',COLLECTION='collection',EER_TYPE='type',EER_BASKET='basket')
    return {'field_codelists':fields,'codelists':{'freq':{'D':'Daily','M':'Monthly'},'area':{'US':'United States'},
        'unit':{'368':'Per cent per year','882':'Index, 2020 = 100'},'mult':{'0':'Units','3':'Thousands'},
        'status':{'A':'Normal','M':'Cannot exist','B':'Break','P':'Provisional','F':'Forecast'},
        'conf':{'F':'Free','C':'Confidential'},'collection':{'A':'Average','E':'End'},
        'type':{'R':'Real','N':'Nominal'},'basket':{'B':'Broad','N':'Narrow'}}}


def data(kind='policy',observations=None,series_extra='',group_unit='882',dataset_extra=''):
    cfg=mod.CONFIG[kind]
    if observations is None: observations=[('2026-09-08','-0.125','A')]
    obs=''.join('<Obs TIME_PERIOD="'+period+'" OBS_VALUE="'+value+'" OBS_STATUS="'+status+'" OBS_CONF="F" />'
                for period,value,status in observations)
    if kind=='policy': group='';series='FREQ="D" REF_AREA="US" SOURCE_REF="Fed" COMPILATION="Past proxy; current target" SUPP_INFO_BREAKS="Literal &amp; break"';ds='UNIT_MULT="0" UNIT_MEASURE="368"'
    else: group='<Group xsi:type="ns1:Sibling" EER_TYPE="R" EER_BASKET="B" REF_AREA="US" UNIT_MEASURE="'+group_unit+'" />';series='FREQ="M" EER_TYPE="R" EER_BASKET="B" REF_AREA="US" COLLECTION="A"';ds=''
    return (f'<m:StructureSpecificData xmlns:m="{mod.NS["m"]}" xmlns:c="{mod.NS["c"]}" '
        f'xmlns:xsi="{mod.XSI[1:-1]}" xmlns:ss="{mod.SS[1:-1]}" xmlns:ns1="urn:test">'
        '<m:Header><m:Test>false</m:Test><m:Prepared>2026-09-14T16:00:00Z</m:Prepared>'
        f'<m:Structure><c:StructureUsage><Ref agencyID="BIS" id="{cfg["flow"]}" version="1.0" />'
        '</c:StructureUsage></m:Structure><m:DataSetAction>Information</m:DataSetAction></m:Header>'
        f'<m:DataSet ss:structureRef="BIS_{cfg["flow"]}_1_0" {ds} {dataset_extra}>{group}<Series {series} {series_extra}>'
        f'{obs}</Series></m:DataSet></m:StructureSpecificData>').encode()


def parse(raw,kind='policy'):
    return mod.parse_data(raw,kind,structure(kind),'2026-09-15',areas=('US',))


def test_signed_exact_decimal_source_text_and_national_methodology():
    rows,meta=parse(data());row=rows[0]
    assert str(row['value'])=='-0.125000000000'
    assert row['provider_value_text']=='-0.125' and row['unit_label']=='Per cent per year'
    assert row['source_ref']=='Fed' and row['compilation']=='Past proxy; current target'
    assert row['supp_info_breaks']=='Literal & break'
    assert meta['series']['D.US']['series_attributes']['SUPP_INFO_BREAKS']=='Literal & break'


def test_missing_nan_not_zero_and_status_retained():
    rows,_=parse(data(observations=[('2026-09-08','NaN','M')]))
    assert rows[0]['value'] is None and rows[0]['provider_value_text']=='NaN'
    assert rows[0]['obs_status']=='M' and rows[0]['value_status']=='SOURCE_MISSING'


def test_prebreak_and_provisional_source_fields_retained():
    raw=data(observations=[('2026-09-08','1.25','P')]).replace(b'OBS_STATUS="P"',b'OBS_STATUS="P" OBS_PRE_BREAK="1.234567891234"')
    rows,_=parse(raw)
    assert str(rows[0]['pre_break_value'])=='1.234567891234'
    assert rows[0]['obs_status']=='P' and json.loads(rows[0]['source_observation_attributes_json'])['OBS_PRE_BREAK']=='1.234567891234'


def test_eer_group_inheritance_and_month_labels():
    rows,meta=parse(data('eer',[('2026-07','100.12','A')]),'eer')
    assert rows[0]['unit_measure']=='882' and rows[0]['unit_label']=='Index, 2020 = 100'
    assert rows[0]['date']=='2026-07-01' and rows[0]['period_end']=='2026-07-31'
    assert rows[0]['collection']=='A' and rows[0]['unit_mult'] is None
    assert meta['series']['M.R.B.US']['group_attributes'][0]['UNIT_MEASURE']=='882'


def test_unfinished_month_is_not_certified_complete():
    with pytest.raises(ValueError,match='INCOMPLETE_PROVIDER_MONTH'):
        parse(data('eer',[('2026-09','100.12','A')]),'eer')


@pytest.mark.parametrize('mutator,message',[
    (lambda r:r.replace(b'id="WS_CBPOL"',b'id="OTHER"'),'DATAFLOW_REFERENCE'),
    (lambda r:r.replace(b'UNIT_MULT="0"',b'UNIT_MULT="3"'),'RATE_UNIT_MULT'),
    (lambda r:r.replace(b'OBS_CONF="F"',b'OBS_CONF="C"'),'NONPUBLIC'),
    (lambda r:r.replace(b'OBS_STATUS="A"',b'OBS_STATUS="M"'),'MISSING_VALUE_STATUS'),
    (lambda r:r.replace(b'OBS_VALUE="-0.125"',b'OBS_VALUE="NaN"'),'MISSING_VALUE_STATUS'),
    (lambda r:r.replace(b'OBS_VALUE="-0.125"',b'OBS_VALUE="1e3"'),'UNRECOGNIZED'),
    (lambda r:r.replace(b'OBS_STATUS="A"',b'OBS_STATUS="Z"'),'UNKNOWN_CODE'),
    (lambda r:r.replace(b'TIME_PERIOD="2026-09-08"',b'TIME_PERIOD="2026-09-16"'),'OUTSIDE_REQUESTED'),
    (lambda r:r.replace(b'<Obs ',b'<Obs UNKNOWN="x" '),'UNDECLARED_ATTRIBUTE'),
    (lambda r:b'<!DOCTYPE x [<!ENTITY y "z">]>'+r,'XML_EXTERNAL'),
    (lambda r:r.replace(b'</m:StructureSpecificData>',b'<Footer /></m:StructureSpecificData>'),'FOOTER'),
])
def test_fail_closed_on_source_contract_conflicts(mutator,message):
    with pytest.raises(ValueError,match=message):parse(mutator(data()))


def test_duplicate_period_and_missing_country_fail():
    with pytest.raises(ValueError,match='DUPLICATE_SERIES_PERIOD'):
        parse(data(observations=[('2026-09-08','1','A')]*2))
    with pytest.raises(ValueError,match='COUNTRY_SET_INCOMPLETE'):
        mod.parse_data(data(),'policy',structure('policy'),'2026-09-15',areas=('US','AU'))


def test_group_unit_conflict_rejected():
    with pytest.raises(ValueError,match='CONFLICTING_INHERITED_ATTRIBUTE'):
        parse(data('eer',[('2026-07','100','A')],dataset_extra='UNIT_MEASURE="368"'),'eer')


def test_latest_compares_all_observation_and_method_fields():
    rows,meta=parse(data(observations=[('2026-09-07','1','A'),('2026-09-08','1','A')]))
    latest,lmeta=parse(data(observations=[('2026-09-08','1','A')]))
    assert mod.validate_latest(rows,meta,latest,lmeta,'policy','2026-09-15')[0]['latest_status']=='EXACT_MATCH_OFFICIAL_LAST_N_1'
    changed=deepcopy(latest);changed[0]['obs_status']='P'
    with pytest.raises(ValueError,match='LATEST_OBSERVATION_DIFFERS'):mod.validate_latest(rows,meta,changed,lmeta,'policy','2026-09-15')
    changed_meta=deepcopy(lmeta);changed_meta['series']['D.US']['series_attributes']['SOURCE_REF']='Changed'
    with pytest.raises(ValueError,match='LATEST_SERIES_METADATA_DIFFERS'):mod.validate_latest(rows,meta,latest,changed_meta,'policy','2026-09-15')


def test_month_gap_rejected_daily_absence_not_imputed():
    rows,meta=parse(data('eer',[('2026-05','99','A'),('2026-07','100','A')]),'eer')
    latest,lmeta=parse(data('eer',[('2026-07','100','A')]),'eer')
    with pytest.raises(ValueError,match='MONTHLY_INTERNAL_PERIOD_MISSING'):
        mod.validate_latest(rows,meta,latest,lmeta,'eer','2026-09-15')
    rows,meta=parse(data(observations=[('2026-09-04','1','A'),('2026-09-07','1','A')]))
    latest,lmeta=parse(data(observations=[('2026-09-07','1','A')]))
    stats=mod.validate_latest(rows,meta,latest,lmeta,'policy','2026-09-15')[0]
    assert stats['calendar_dates_without_source_record']==2 and len(rows)==2


def test_decimal_arrow_roundtrip_keeps_null_and_full_precision():
    values=[mod.exact_number('12345678901234567890123456.123456789012'),mod.exact_number('NaN')]
    table=pa.array(values,pa.decimal128(38,12))
    assert table.to_pylist()==values
    with pytest.raises(ValueError,match='INEXACT'):mod.exact_number('0.0000000000001')


def test_access_denial_is_immutable_and_stops_next_request(tmp_path,monkeypatch):
    @dataclass
    class Raw:
        status:str='FAILED'
        local_path:str=''
    class Archive:
        def acquire_url(self,url,*args):
            try:self._download_once(url,60)
            except ValueError:return Raw()
    class Response:
        status_code=403;headers={}
        def __enter__(self):return self
        def __exit__(self,*args):return False
    calls=[]
    monkeypatch.setattr(mod.requests,'get',lambda *a,**k:(calls.append(a),Response())[1])
    monkeypatch.setattr(mod.common,'archive_module',lambda root:Archive())
    monkeypatch.setattr(mod.time,'sleep',lambda _:None)
    monkeypatch.setattr(mod.shutil,'disk_usage',lambda path:SimpleNamespace(free=100*1024**3))
    paths=SimpleNamespace(repo_root=tmp_path,cache_root=tmp_path/'cache',data_root=tmp_path/'data',results_root=tmp_path/'results')
    for p in [paths.cache_root,paths.data_root]:p.mkdir()
    with pytest.raises(ValueError,match='ACQUISITION_FAILED'):mod.fetch(paths,'test','first','https://stats.bis.org/approved')
    with pytest.raises(ValueError,match='PRIOR_ACCESS_DENIAL'):mod.fetch(paths,'test','second','https://stats.bis.org/second')
    assert len(calls)==1 and (mod.roots(paths,'test')[0]/'access_stop.json').exists()


def test_structure_rejects_unknown_message_or_flow():
    with pytest.raises(ValueError,match='UNEXPECTED_SDMX_MESSAGE'):mod.parse_structure(b'<html />','policy')
    with pytest.raises(ValueError,match='UNEXPECTED_STRUCTURE_COUNT'):
        mod.parse_structure(('<m:Structure xmlns:m="'+mod.NS['m']+'"/>').encode(),'eer')


def test_raw_receipt_binds_run_identity_and_exact_byte_count(tmp_path):
    paths=SimpleNamespace(cache_root=tmp_path/'cache',results_root=tmp_path/'results')
    report,rawroot=mod.roots(paths,'test');rawroot.mkdir(parents=True)
    path=rawroot/'fixture.source';path.write_bytes(b'synthetic')
    raw={'status':'DOWNLOADED','local_path':str(path),'source_reference':'https://stats.bis.org/approved',
        'sha256':mod.common.sha256(path),'retrieval_timestamp_utc':'2026-09-14T16:00:00Z',
        'event_family':mod.FAMILY,'document_kind':'BIS_FIXTURE','source':'BIS_OFFICIAL'}
    side={k:v for k,v in raw.items() if k not in {'status','local_path'}};side['byte_count']=9
    path.with_suffix('.json').write_text(json.dumps(side))
    receipt={'raw':raw,'url':raw['source_reference'],'name':'fixture',
        'response':{'status':200,'observed_at_utc':'2026-09-14T16:00:00Z','headers':{'Content-Length':'9'}}}
    assert mod.raw_file(receipt,paths,raw['source_reference'],'test','fixture')==path.resolve()
    with pytest.raises(ValueError,match='RAW_IDENTITY'):mod.raw_file(receipt,paths,raw['source_reference'],'different','fixture')
    side['byte_count']=8;path.with_suffix('.json').write_text(json.dumps(side))
    with pytest.raises(ValueError,match='SIDECAR_MISMATCH'):mod.raw_file(receipt,paths,raw['source_reference'],'test','fixture')
