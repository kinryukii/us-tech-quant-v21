from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse


USER_AGENT = "FAST6-DATA-R1/1.0 official-macro-archive"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def classify_http_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "NOT_FOUND"
        if exc.code == 429:
            return "RATE_LIMIT"
        return "NETWORK"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "NETWORK"
    return "UNSUPPORTED"


@dataclass(frozen=True)
class RawDocument:
    event_family: str
    source: str
    source_reference: str
    document_kind: str
    local_path: str | None
    sha256: str | None
    retrieval_timestamp_utc: str | None
    status: str
    failure_class: str | None = None
    error: str | None = None


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def _download_once(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _post_json_once(url: str, payload: bytes, timeout: int) -> bytes:
    request = urllib.request.Request(
        url, data=payload,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def acquire_url(
    url: str,
    family: str,
    source: str,
    kind: str,
    raw_root: Path,
    timeout: int,
    retries: int,
    backoff: float,
) -> RawDocument:
    family_root = raw_root / family.lower()
    family_root.mkdir(parents=True, exist_ok=True)
    key = cache_key(url)
    payload_path = family_root / f"{key}.source"
    meta_path = family_root / f"{key}.json"
    if payload_path.exists() or meta_path.exists():
        if not (payload_path.exists() and meta_path.exists()):
            raise RuntimeError("SOURCE_DATA_MUTATION: incomplete raw cache pair")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        actual = sha256_file(payload_path)
        if meta.get("sha256") != actual or meta.get("source_reference") != url:
            raise RuntimeError("SOURCE_DATA_MUTATION: cached document hash/reference mismatch")
        return RawDocument(
            family, source, url, kind, str(payload_path), actual,
            meta.get("retrieval_timestamp_utc"), "CACHED"
        )
    last: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            data = _download_once(url, timeout)
            digest = sha256_bytes(data)
            retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            payload_path.write_bytes(data)
            meta = {
                "event_family": family, "source": source, "source_reference": url,
                "document_kind": kind, "retrieval_timestamp_utc": retrieved,
                "sha256": digest, "byte_count": len(data)
            }
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return RawDocument(family, source, url, kind, str(payload_path), digest, retrieved, "DOWNLOADED")
        except BaseException as exc:  # failure is recorded and family processing continues
            last = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    assert last is not None
    return RawDocument(
        family, source, url, kind, None, None, None, "FAILED",
        classify_http_error(last), f"{type(last).__name__}: {last}"
    )


def acquire_bls_api(config: dict[str, Any]) -> RawDocument:
    api = config["bls_api"]
    endpoint = api["endpoint"]
    payload = json.dumps({
        "seriesid": list(api["series"]),
        "startyear": api["start_year"],
        "endyear": api["end_year"],
        "catalog": True,
    }, separators=(",", ":"), sort_keys=True).encode("utf-8")
    raw_root = Path(config["raw_root"]) / "bls_api"
    raw_root.mkdir(parents=True, exist_ok=True)
    key = cache_key(endpoint + "\n" + payload.decode("utf-8"))
    payload_path = raw_root / f"{key}.json"
    meta_path = raw_root / f"{key}.meta.json"
    if payload_path.exists() or meta_path.exists():
        if not (payload_path.exists() and meta_path.exists()):
            raise RuntimeError("SOURCE_DATA_MUTATION: incomplete BLS API cache pair")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        actual = sha256_file(payload_path)
        if meta.get("sha256") != actual or meta.get("request_sha256") != sha256_bytes(payload):
            raise RuntimeError("SOURCE_DATA_MUTATION: BLS API cache hash/request mismatch")
        return RawDocument(
            "BLS_API", "U.S. Bureau of Labor Statistics Public Data API", endpoint,
            "bls_api_values", str(payload_path), actual,
            meta.get("retrieval_timestamp_utc"), "CACHED"
        )
    net = config["network"]
    last: BaseException | None = None
    for attempt in range(int(net["max_retries"]) + 1):
        try:
            data = _post_json_once(endpoint, payload, int(net["timeout_seconds"]))
            parsed = json.loads(data.decode("utf-8"))
            if parsed.get("status") != "REQUEST_SUCCEEDED":
                raise ValueError(f"BLS API status {parsed.get('status')}: {parsed.get('message')}")
            digest = sha256_bytes(data)
            retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            payload_path.write_bytes(data)
            meta_path.write_text(json.dumps({
                "source_reference": endpoint, "request_sha256": sha256_bytes(payload),
                "series_ids": list(api["series"]), "retrieval_timestamp_utc": retrieved,
                "sha256": digest, "byte_count": len(data),
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return RawDocument(
                "BLS_API", "U.S. Bureau of Labor Statistics Public Data API", endpoint,
                "bls_api_values", str(payload_path), digest, retrieved, "DOWNLOADED"
            )
        except BaseException as exc:
            last = exc
            if attempt < int(net["max_retries"]):
                time.sleep(float(net["backoff_seconds"]) * (attempt + 1))
    assert last is not None
    failure = "PARSE_ERROR" if isinstance(last, (ValueError, json.JSONDecodeError)) else classify_http_error(last)
    return RawDocument(
        "BLS_API", "U.S. Bureau of Labor Statistics Public Data API", endpoint,
        "bls_api_values", None, None, None, "FAILED", failure,
        f"{type(last).__name__}: {last}"
    )


def _official_release_links(doc: RawDocument, adapter: str, label: str, limit: int = 100) -> list[str]:
    if not doc.local_path or doc.status == "FAILED":
        return []
    raw = Path(doc.local_path).read_bytes().decode("utf-8", errors="replace")
    parser = LinkParser()
    parser.feed(raw)
    base = doc.source_reference
    host = urlparse(base).hostname
    results: list[str] = []
    for href, text in parser.links:
        url = urljoin(base, href)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != host:
            continue
        low = (url + " " + text).lower()
        keep = False
        if adapter == "fomc":
            keep = "monetary20" in low and ("statement" in low or url.endswith("a.htm"))
        elif adapter == "bea":
            keep = "/news/" in low and label.lower() in low
        if keep and url not in results:
            results.append(url)
        if len(results) >= limit:
            break
    return results


def acquire_all(config: dict[str, Any]) -> tuple[list[RawDocument], list[dict[str, Any]]]:
    raw_root = Path(config["raw_root"])
    net = config["network"]
    documents: list[RawDocument] = []
    source_rows: list[dict[str, Any]] = []
    url_cache: dict[str, RawDocument] = {}
    bls_api_doc = acquire_bls_api(config)
    documents.append(bls_api_doc)
    for family, spec in config["event_families"].items():
        if spec["adapter"] == "bls":
            source_rows.append({
                "event_family": family, "source": spec["source"], "adapter": "bls_api_plus_static_csv",
                "official_urls": [config["bls_api"]["endpoint"]],
                "static_calendar_path": config["bls_static_calendar_path"],
                "document_count": int(bls_api_doc.status != "FAILED"),
                "failure_count": int(bls_api_doc.status == "FAILED"),
                "automated_bls_html_ics_requests": 0,
            })
            continue
        family_docs: list[RawDocument] = []
        index_urls = list(spec.get("calendar_urls", []))
        if spec.get("archive_url"):
            index_urls.append(spec["archive_url"])
        for url in index_urls:
            if url in url_cache:
                base = url_cache[url]
                doc = RawDocument(
                    family, spec["source"], url, "calendar" if "schedule" in url or "calendar" in url else "archive_index",
                    base.local_path, base.sha256, base.retrieval_timestamp_utc, base.status,
                    base.failure_class, base.error
                )
            else:
                kind = "calendar" if "schedule" in url or "calendar" in url or "historical" in url else "archive_index"
                doc = acquire_url(url, family, spec["source"], kind, raw_root, int(net["timeout_seconds"]), int(net["max_retries"]), float(net["backoff_seconds"]))
                url_cache[url] = doc
            documents.append(doc)
            family_docs.append(doc)
        followed: list[str] = []
        for index_doc in family_docs:
            if index_doc.document_kind in {"archive_index", "calendar"}:
                followed.extend(_official_release_links(index_doc, spec["adapter"], spec["release_label"]))
        for url in sorted(set(followed))[:100]:
            doc = acquire_url(url, family, spec["source"], "release_document", raw_root, int(net["timeout_seconds"]), int(net["max_retries"]), float(net["backoff_seconds"]))
            documents.append(doc)
        source_rows.append({
            "event_family": family, "source": spec["source"], "adapter": spec["adapter"],
            "official_urls": index_urls, "document_count": sum(d.event_family == family and d.status != "FAILED" for d in documents),
            "failure_count": sum(d.event_family == family and d.status == "FAILED" for d in documents)
        })
    return documents, source_rows


def documents_as_dicts(documents: list[RawDocument]) -> list[dict[str, Any]]:
    return [asdict(d) for d in documents]
