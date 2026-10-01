"""Narrow, reviewed corporate-action continuity for display, never PIT identity.

CHPT's issuer 2025-07-28 announcement/8-K confirms common stock continuity,
1-for-20 consolidation and new CUSIP 15961R303. The old common-stock CUSIP
15961R105 is identified in the issuer's SEC Schedule 13G. These public sources
were reviewed 2026-09-24; no local HTML snapshot is claimed. Runtime eligibility
also requires the published price lineage AND its exact recorded action evidence.
"""
from apps.demo_console.adapters import updated_research_reader as base

IDS = ['15961R105', '15961R303']
REHAB_SHA = '25cd03aaba55c227c81d5a89203eb336c6c728d173c3c4894e42fbae49995355'
SOURCES = [
    'https://www.sec.gov/Archives/edgar/data/1777393/000117152022000120/eps10008.htm',
    'https://www.sec.gov/Archives/edgar/data/1777393/000177739325000144/chpt-20250725.htm',
    'https://investors.chargepoint.com/news/news-details/2025/ChargePoint-Announces-Reverse-Stock-Split/default.aspx',
]


def _json(ref):
    path, sha = base._ref(ref)
    if base._hash(path) != sha:
        raise ValueError('IDENTITY_DISPLAY_HASH_CHANGED')
    return base._json(path)


def read_identity_chain(a2_reference, ticker):
    if ticker != 'CHPT':
        return {'status': 'UNVERIFIED', 'ticker': ticker}
    try:
        a2 = _json(a2_reference)
        if a2.get('source_id') != 'A2_UPDATED_RESEARCH':
            raise ValueError('IDENTITY_DISPLAY_PARENT_INVALID')
        h = _json(a2['ranking_manifest'])
        inputs = _json(h['price_manifest'])
        entries = [row for row in inputs['lineage'] if row['ticker'] == ticker]
        if len(entries) != 1 or set(entries[0].get('cusips', [])) != set(IDS):
            raise ValueError('IDENTITY_DISPLAY_LINEAGE_CHANGED')
        ref = entries[0]['rehab']
        path, sha = base._ref(ref)
        if sha != REHAB_SHA or base._hash(path) != sha:
            raise ValueError('IDENTITY_DISPLAY_REHAB_CHANGED')
        rows = base.pq.read_table(path).to_pylist()
        if len(rows) != 1 or any(rows[0].get(k) != v for k, v in {
                'code': 'US.CHPT', 'ex_div_date': '2025-07-28',
                'join_base': 20, 'join_ert': 1,
                'forward_adj_factorA': 20., 'forward_adj_factorB': 0.}.items()):
            raise ValueError('IDENTITY_DISPLAY_ACTION_CHANGED')
        return dict(status='VERIFIED', ticker=ticker, security_ids=IDS[:],
            parent_a2_manifest={k: a2_reference[k] for k in ('path', 'sha256')},
            evidence_refs=[a2['ranking_manifest'], h['price_manifest'], ref],
            source_urls=SOURCES[:], event_date='2025-07-28',
            old_security_id=IDS[0], new_security_id=IDS[1],
            old_shares=20, new_shares=1, scope='DISPLAY_ONLY_COMPANY_CONTINUITY',
            evidence_review_date='2026-09-24',
            limitation='PIT 13F security IDs remain as reported; filing-pool changes need not coincide with the split date.')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return dict(status='UNVERIFIED', ticker=ticker, error=str(exc))


def validate_identity_chain(chain):
    if not isinstance(chain, dict) or chain.get('status') != 'VERIFIED':
        raise ValueError('IDENTITY_DISPLAY_CHAIN_UNVERIFIED')
    fresh = read_identity_chain(chain['parent_a2_manifest'], chain['ticker'])
    if fresh != chain:
        raise ValueError('IDENTITY_DISPLAY_CHAIN_CHANGED')
    return fresh
