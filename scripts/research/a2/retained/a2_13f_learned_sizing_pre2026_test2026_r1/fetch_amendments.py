"""Bounded SEC accession fetch for amendment semantics, into this task only."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent
RAW = OUT / "sec_amendment_raw"
UA_SOURCE = Path("D:/us-tech-quant/scripts/v22/stage_sec_pit_taxonomy.py")


def existing_ua() -> str:
    for node in ast.parse(UA_SOURCE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "DEFAULT_USER_AGENT" for target in node.targets):
            value = ast.literal_eval(node.value)
            if "@" not in value:
                raise RuntimeError("SEC_USER_AGENT_LACKS_CONTACT")
            return value
    raise RuntimeError("NO_EXISTING_SEC_USER_AGENT")


def fetch_one(url: str, path: Path, ua: str) -> tuple[str, int | None]:
    if path.exists():
        payload = path.read_bytes()
        return "LOCAL_REUSED", len(payload)
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=45)
            if response.status_code in (403, 429):
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return f"HTTP_{response.status_code}_STOP", None
            response.raise_for_status()
            if not response.content.startswith(b"<SEC-DOCUMENT>"):
                return "NOT_SEC_DOCUMENT_STOP", None
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return "DOWNLOADED", len(response.content)
        except requests.RequestException as exc:
            if attempt == 2 or "10013" in str(exc) or "Permission" in str(exc):
                return "NETWORK_UNAVAILABLE_STOP", None
            time.sleep(2 ** (attempt + 1))
    return "RETRY_LIMIT_STOP", None


def classify(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    match = re.search(r"<amendmentType>(.*?)</amendmentType>", text, flags=re.I | re.S)
    if match:
        value = re.sub(r"\s+", " ", match.group(1)).strip().upper()
        if "RESTATEMENT" in value:
            return "RESTATEMENT"
        if "NEW" in value or "ADDITION" in value:
            return "NEW_HOLDINGS_SUPPLEMENT"
        return "UNRECOGNIZED:" + value[:80]
    return "UNKNOWN_MISSING_AMENDMENT_TYPE"


def main() -> None:
    candidates = pd.read_csv(OUT / "AMENDMENT_CANDIDATES.csv", dtype=str)
    ua = existing_ua()
    receipts = []
    for row in candidates.itertuples(index=False):
        accession = str(row.ACCESSION_NUMBER)
        path = RAW / (accession + ".txt")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(row.CIK)}/{accession.replace('-', '')}/{accession}.txt"
        status, size = fetch_one(url, path, ua)
        record = {"accession": accession, "cik": row.CIK, "report_period": row.PERIODOFREPORT,
                  "filed_date": row.FILING_DATE, "source_url": url, "fetch_status": status,
                  "bytes": size, "amendment_type": None, "sha256": None, "accepted_at_utc": None}
        if path.exists():
            data = path.read_bytes()
            record["sha256"] = hashlib.sha256(data).hexdigest()
            record["amendment_type"] = classify(data)
            accepted = re.search(rb"<ACCEPTANCE-DATETIME>(\d{14})", data)
            if accepted:
                record["accepted_at_utc"] = str(pd.Timestamp(datetime.strptime(accepted.group(1).decode(), "%Y%m%d%H%M%S"), tz="America/New_York").tz_convert("UTC"))
        receipts.append(record)
        pd.DataFrame(receipts).to_csv(OUT / "AMENDMENT_FETCH_RECEIPTS.csv", index=False)
        if status.endswith("STOP"):
            break
        time.sleep(1.0)  # below task's 2 requests/second ceiling, including shared-use margin
    print(json.dumps({"attempted": len(receipts), "statuses": pd.DataFrame(receipts).fetch_status.value_counts().to_dict(),
                      "types": pd.DataFrame(receipts).amendment_type.value_counts().to_dict()}, indent=2))


if __name__ == "__main__":
    main()
