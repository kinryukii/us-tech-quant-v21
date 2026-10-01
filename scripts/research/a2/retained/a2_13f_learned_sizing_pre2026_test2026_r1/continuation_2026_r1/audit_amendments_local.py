"""Targeted accession metadata from existing SEC submissions JSON; no bulk reparse."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
BASE = OUT.parent
SEC = Path("D:/us-tech-quant-cache/13f_pit_v1/sec")

def main():
    candidates = pd.read_csv(BASE / "AMENDMENT_CANDIDATES.csv", dtype=str).fillna("")
    wanted = set(candidates.ACCESSION_NUMBER)
    found = {}
    for source in SEC.glob("*.json"):
        data = json.loads(source.read_text(encoding="utf-8"))
        recent = data.get("filings", {}).get("recent", {})
        for pos, accession in enumerate(recent.get("accessionNumber", [])):
            if accession in wanted:
                found[accession] = {"accession": accession, "cik": data.get("cik"),
                                    "accepted_at": recent.get("acceptanceDateTime", [])[pos],
                                    "filing_date": recent.get("filingDate", [])[pos],
                                    "form": recent.get("form", [])[pos],
                                    "primary_document": recent.get("primaryDocument", [])[pos],
                                    "primary_description": recent.get("primaryDocDescription", [])[pos],
                                    "source_json": str(source)}
    rows=[]
    for candidate in candidates.itertuples(index=False):
        rec=found.get(candidate.ACCESSION_NUMBER,{})
        rows.append({"accession":candidate.ACCESSION_NUMBER,"report_quarter":candidate.report_quarter,
                     "filing_date_original":candidate.filing_date,"accepted_at_local":rec.get("accepted_at",""),
                     "local_form":rec.get("form",""),"primary_document":rec.get("primary_document",""),
                     "primary_description":rec.get("primary_description",""),"amendment_type":"UNKNOWN_COVERPAGE_NOT_CACHED",
                     "source_json":rec.get("source_json",""),"coverpage_source":"ABSENT_IN_REDUCED_SEC_PACKAGE"})
    frame=pd.DataFrame(rows)
    frame.to_csv(OUT/"AMENDMENT_LOCAL_METADATA.csv",index=False)
    print({"amendment_candidates":len(frame),"accepted_at_found":int(frame.accepted_at_local.ne("").sum()),
           "primary_document_found":int(frame.primary_document.ne("").sum()),
           "amendment_type_found":int(frame.amendment_type.ne("UNKNOWN_COVERPAGE_NOT_CACHED").sum())})

if __name__=="__main__":
    main()
