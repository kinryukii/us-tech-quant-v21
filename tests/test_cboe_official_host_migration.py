"""Synthetic official-link selection; no network calls or historical data reads."""
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / 'scripts/storage/refresh_public_sources.py'
SPEC = importlib.util.spec_from_file_location('cboe_host_migration_subject', SOURCE)
public = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append((dict(attrs)['href'], ''))


@pytest.mark.parametrize('host', ['cdn-api.cboe.com', 'cdn.cboe.com'])
def test_selects_only_actual_official_directory_link(host):
    url = f'https://{host}/api/global/us_indices/daily_prices/VVIX_History.csv'
    assert public.select_cboe_history_url('VVIX', {url}) == url


@pytest.mark.parametrize('url', [
    'https://cdn-api.cboe.com.evil.test/api/global/us_indices/daily_prices/VVIX_History.csv',
    'https://example.test/api/global/us_indices/daily_prices/VVIX_History.csv',
    'http://cdn-api.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv',
    'https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv',
])
def test_rejects_other_hosts_schemes_and_symbols(url):
    with pytest.raises(ValueError, match='CBOE_HISTORY_NOT_EXPLICITLY_LINKED'):
        public.select_cboe_history_url('VVIX', {url})


@pytest.mark.parametrize('host', ['cdn-api.cboe.com', 'cdn.cboe.com'])
def test_validation_binds_each_host_to_frozen_page_and_cache_sidecar(tmp_path, host):
    folder = tmp_path / 'cboe_indices'
    folder.mkdir()

    def cache_key(url):
        return hashlib.sha256(url.encode()).hexdigest()

    def raw(url, body):
        path = folder / (cache_key(url) + '.source')
        path.write_bytes(body)
        metadata = {'source_reference': url, 'source': 'CBOE_OFFICIAL',
                    'sha256': hashlib.sha256(body).hexdigest(),
                    'retrieval_timestamp_utc': '2026-09-23T08:00:00Z'}
        path.with_suffix('.json').write_text(json.dumps(metadata), encoding='utf-8')
        return {**metadata, 'local_path': str(path), 'status': 'DOWNLOADED'}

    urls = [f'https://{host}/api/global/us_indices/daily_prices/{symbol}_History.csv'
            for symbol in public.CBOE_INDICES]
    page = ''.join(f'<a href="{url}">CSV</a>' for url in urls).encode()
    acquisition = {'target': '2026-09-23', 'page': raw(public.CBOE_HISTORY_PAGE, page),
                   'items': [{'symbol': symbol, 'raw': raw(url, b'DATE,CLOSE\n09/22/2026,1\n')}
                             for symbol, url in zip(public.CBOE_INDICES, urls)]}
    capture = SimpleNamespace(cache_key=cache_key, LinkParser=Links)
    public.validate_cboe_acquisition(acquisition, capture, tmp_path, '2026-09-23')
    acquisition['page'] = raw(public.CBOE_HISTORY_PAGE, b'<html>No history links</html>')
    with pytest.raises(ValueError, match='CBOE_HISTORY_NOT_EXPLICITLY_LINKED'):
        public.validate_cboe_acquisition(acquisition, capture, tmp_path, '2026-09-23')
