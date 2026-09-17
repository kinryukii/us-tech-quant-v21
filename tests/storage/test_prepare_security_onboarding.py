import sqlite3

import pandas as pd

from scripts.storage.build_data_catalog import SCHEMA
from scripts.storage.prepare_security_onboarding import prepare
from scripts.storage.storage_r2a import DataStore, StoragePaths


def test_exact_identity_queue_preserves_unknowns_and_simultaneous_conflicts(tmp_path):
    paths = StoragePaths(**{name: tmp_path / name for name in (
        'repo_root', 'data_root', 'cache_root', 'daily_root', 'backtest_root', 'results_root', 'envs_root')})
    store = DataStore(paths)
    store.catalog_path.parent.mkdir(parents=True)
    with sqlite3.connect(store.catalog_path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany('INSERT INTO catalog_metadata VALUES (?,?)',
                         [('schema_version', '1'), ('catalog_role', 'REBUILDABLE_FILE_INDEX')])
    root = paths.data_root / 'quarter'
    root.mkdir(parents=True)
    pd.DataFrame({'cusip': ['000000001', '000000002', '000000003', '000000004'],
                  'issuer_name': ['Known', 'Known', 'Class A', 'Class B'],
                  'quarter': ['2026Q2'] * 4, 'effective_date': ['2026-08-21'] * 4}).to_parquet(root / 'quarter_universe.parquet', index=False)
    identities = root / 'identities.parquet'
    pd.DataFrame({'cusip': ['000000001', '000000003', '000000004'],
                  'ticker': ['ABC', 'DEF', 'DEF'], 'moomoo_transport_code': ['US.ABC', 'US.DEF', 'US.DEF'],
                  'mapping_status': ['RESOLVED'] * 3, 'mapping_source': ['existing'] * 3}).to_parquet(identities, index=False)
    history = root / 'history.parquet'
    pd.DataFrame({'cusip': ['000000001', '000000003']}).to_parquet(history, index=False)
    result = prepare(store, root, identities, history)
    frame = pd.read_parquet(result['path']).set_index('cusip')
    assert result['new_historical_cusips'] == 2
    assert frame.loc['000000001', 'intake_status'] == 'EXISTING_MAPPING_REQUIRES_LIFECYCLE_REVIEW'
    assert frame.loc['000000002', 'intake_status'] == 'PENDING_IDENTITY'
    assert pd.isna(frame.loc['000000002', 'ticker'])
    assert frame.loc[['000000003', '000000004'], 'intake_status'].eq('PENDING_SIMULTANEOUS_IDENTITY_REVIEW').all()
    assert store.metadata('security_onboarding_external25')['lineage']['strategy_membership_changed'] is False
