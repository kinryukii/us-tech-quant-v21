from pathlib import Path
import urllib.request, urllib.error, hashlib, json, datetime
out=Path('a2_qualification_holdings_v1_20260927/evidence/identity'); (out/'official_sources').mkdir(exist_ok=True)
urls={
'slmt_old_cusip_class_6k':'https://www.sec.gov/Archives/edgar/data/1939965/000121390025056896/ea0246577-6k_brera.htm',
'slmt_old_cusip_class_index':'https://www.sec.gov/Archives/edgar/data/1939965/000121390025056896/0001213900-25-056896-index.html',
'bynd_old_cusip_class_13g':'https://www.sec.gov/Archives/edgar/data/1655210/000165521025000016/xslSCHEDULE_13G_X01/primary_doc.xml',
'bynd_old_cusip_class_index':'https://www.sec.gov/Archives/edgar/data/1655210/000165521025000016/0001655210-25-000016-index.html',
'dte_corporate_units_prospectus':'https://www.sec.gov/Archives/edgar/data/936340/000119312519278848/d813800d424b2.htm',
'dte_common_cusip_index':'https://www.sec.gov/Archives/edgar/data/936340/000142284921000094/0001422849-21-000094-index.html',
'dte_common_cusip_13g':'https://www.sec.gov/Archives/edgar/data/936340/000142284921000094/SEC13G_Filing.htm',
'exas_merger_8k':'https://www.sec.gov/Archives/edgar/data/1124140/000119312526118700/d128802d8k.htm',
'exas_merger_index':'https://www.sec.gov/Archives/edgar/data/1124140/000119312526118700/0001193125-26-118700-index.html',
'dte_prospectus_index':'https://www.sec.gov/Archives/edgar/data/936340/000119312519278848/0001193125-19-278848-index.html'}
prior=json.loads((out/'OFFICIAL_FETCH_RECEIPT.json').read_text(encoding='utf-8')) if (out/'OFFICIAL_FETCH_RECEIPT.json').exists() else []
old={r['source_id']:r for r in prior}
rows=[]
for key,url in urls.items():
 dest=out/'official_sources'/f'{key}.html'; row={'source_id':key,'url':url,'retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'artifact_type':'ORIGINAL_HTTP_RESPONSE_BYTES'}
 if dest.exists() and key in old and old[key].get('raw_original_available'):
  rows.append(old[key]); print(key,'REUSED_LOCAL_HASH'); continue
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 identity-audit/1.0','Accept-Encoding':'identity'})
  with urllib.request.urlopen(req,timeout=20) as r: body=r.read(); row.update(status=r.status,content_type=r.headers.get('Content-Type'),response_last_modified=r.headers.get('Last-Modified'))
  dest.write_bytes(body); row.update(local_path=str(dest.resolve()),sha256=hashlib.sha256(body).hexdigest(),size=len(body),raw_original_available=True)
 except Exception as e: row.update(error=repr(e),raw_original_available=False)
 rows.append(row); print(key,row.get('status',row.get('error')))
(out/'OFFICIAL_FETCH_RECEIPT.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
