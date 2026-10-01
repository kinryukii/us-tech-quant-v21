"""One bounded official SEC primary-document metadata request."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from fetch_amendments import existing_ua  # noqa: E402

def main():
    row = pd.read_csv(OUT / "AMENDMENT_LOCAL_METADATA.csv", dtype=str).fillna("").iloc[0]
    accession = row.accession
    cik = int(row.cik) if "cik" in row.index and row.cik else 1791786
    url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
           f"{accession.replace('-', '')}/{row.primary_document}")
    record = {"accession": accession, "url": url, "attempts": 1, "status": "", "http_status": None,
              "bytes": 0, "sha256": None}
    try:
        response = requests.get(url, headers={"User-Agent": existing_ua(),
                                             "Accept-Encoding": "gzip, deflate"}, timeout=15)
        record["http_status"] = response.status_code
        if response.status_code == 200 and b"amendment" in response.content.lower():
            raw_path = OUT / "ONE_SEC_AMENDMENT_COVERPAGE.xml"
            raw_path.write_bytes(response.content)
            record.update(status="DOWNLOADED_XML", bytes=len(response.content),
                          sha256=hashlib.sha256(response.content).hexdigest())
        else:
            record["status"] = f"HTTP_{response.status_code}_OR_NON_AMENDMENT_STOP"
    except requests.RequestException as exc:
        record["status"] = "NETWORK_UNAVAILABLE_STOP"
        record["error_type"] = type(exc).__name__
        record["error_excerpt"] = str(exc)[:250]
    (OUT / "ONE_SEC_COVERPAGE_FETCH_RECEIPT.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:record[k] for k in ("accession","status","http_status","attempts")}))

if __name__ == "__main__":
    main()
