"""Pure, outcome-independent admission of inherited event quote masks.

The existing event-quality helper combines quote validity with accounting event
warnings. This thin rule supplies missing provenance/classification only. It
does not execute accounts, change lifecycle events or value NAV. Its loader
reads only explicitly pinned source/population metadata for custody validation.
The caller owns physical source pins and constructs separate base/event masks.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
import math
import numpy as np

TASK_ID = 'V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1'
CLASSES = {
    'A': 'MASK_ONLY_EXACT_RAW_QUOTE_IDENTITY_UNIQUE',
    'B': 'RAW_QUOTE_MISSING_OR_NONFINITE',
    'C': 'SECURITY_IDENTITY_AMBIGUOUS',
    'D': 'OTHER_QUOTE_QUALITY_REASON',
    'E': 'TERMINAL_OR_NONTRADABLE_BY_CONTRACT',
}
START = date(2023, 1, 1)
END = date(2026, 1, 1)


def _day(value):
    if not isinstance(value, str):
        raise ValueError('QUOTE_DOMAIN_DATE_REQUIRED')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('QUOTE_DOMAIN_DATE_NOT_CANONICAL')
    return parsed


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def classify_quote_key(record):
    """Derive A--E from source rows; retain every blocker and mechanism reason.

    ``raw_rows`` are the complete raw ticker/date projection, not a preferred
    row. ``code_tickers`` contains same-date code-to-ticker multiplicity from the
    full source projection. Identity records use start-inclusive/end-exclusive
    intervals, including all reverse-SID-related ticker intervals. An empty explicit independent_quality_flags list must be backed
    by the caller's frozen source construction, never by cash-event legality.
    """
    ticker = record['ticker']; day = _day(record['date'])
    if not isinstance(ticker, str) or not ticker.strip() or not START <= day < END:
        raise ValueError('QUOTE_DOMAIN_KEY_OUTSIDE_FROZEN_WINDOW')
    required = ('masked', 'inherited_event_mask', 'raw_rows', 'identity_records',
                'code_tickers', 'coordinate', 'independent_quality_flags',
                'mechanisms', 'terminal_contracts')
    if any(k not in record for k in required):
        raise ValueError('QUOTE_DOMAIN_EVIDENCE_INCOMPLETE')
    if type(record['masked']) is not bool or type(record['inherited_event_mask']) is not bool:
        raise ValueError('QUOTE_DOMAIN_TYPED_MASK_REQUIRED')
    flags = record['independent_quality_flags']
    if not isinstance(flags, list) or any(not isinstance(x, str) or not x for x in flags):
        raise ValueError('QUOTE_DOMAIN_INDEPENDENT_QUALITY_FLAGS_REQUIRED')
    rows = record['raw_rows']; identities = record['identity_records']
    mechanisms = record['mechanisms']; terminal = record['terminal_contracts']
    if any(not isinstance(x, list) for x in (rows, identities, mechanisms, terminal)):
        raise ValueError('QUOTE_DOMAIN_TYPED_SOURCE_ROWS_REQUIRED')
    reasons = set(); blockers = set(); raw_bad = False; identity_bad = False
    if len(rows) == 0:
        blockers.add('RAW_ROW_MISSING'); raw_bad = True
    elif len(rows) != 1:
        blockers.add('RAW_ROW_NOT_UNIQUE')
    for row in rows:
        if row.get('ticker') != ticker or row.get('date') != record['date']:
            blockers.add('RAW_ROW_KEY_MISMATCH'); identity_bad = True
        for field in ('open', 'close'):
            if not _finite(row.get(field)):
                blockers.add('RAW_' + field.upper() + '_NONFINITE'); raw_bad = True
            elif row[field] <= 0:
                blockers.add('RAW_' + field.upper() + '_NONPOSITIVE')
        code = row.get('code')
        names = record['code_tickers'].get(code) if isinstance(code, str) else None
        if not code or names != [ticker]:
            blockers.add('RAW_CODE_TICKER_BINDING_NOT_UNIQUE'); identity_bad = True
    covering = []
    for row in identities:
        if row.get('ticker') == ticker and _day(row['start']) <= day < _day(row['end']):
            covering.append(row)
    if len(covering) != 1:
        blockers.add('DATED_SECURITY_BINDING_NOT_UNIQUE'); identity_bad = True
    if record['coordinate'] != 'RAW_ACTUAL_SHARE' or any(
            row.get('coordinate') != 'RAW_ACTUAL_SHARE' or not row.get('sid') for row in covering):
        blockers.add('SECURITY_RAW_COORDINATE_UNBOUND'); identity_bad = True
    sids = {row.get('sid') for row in covering}
    reverse = [row for row in identities if row.get('sid') in sids and
               _day(row['start']) <= day < _day(row['end'])]
    if len(covering) == 1 and (len(reverse) != 1 or reverse[0].get('ticker') != ticker):
        blockers.add('DATED_SECURITY_REVERSE_BINDING_NOT_UNIQUE'); identity_bad = True
    terminal_here = any(row.get('ticker') == ticker and row.get('sid') in sids and
                        _day(row['nontradable_from']) <= day for row in terminal)
    if terminal_here:
        blockers.add('TERMINAL_OR_NONTRADABLE_CONTRACT_ACTIVE')
    if not record['masked'] or not record['inherited_event_mask']:
        blockers.add('NOT_INHERITED_MASKED_POPULATION')
    if record['masked'] != record['inherited_event_mask']:
        blockers.add('INHERITED_MASK_PROVENANCE_MISMATCH')
    if not mechanisms or any(row.get('mask_origin') != 'INHERITED_UNSUPPORTED_EVENT' or
                             row.get('ticker') != ticker or row.get('date') != record['date'] or
                             not row.get('source_fingerprint') or not row.get('source_reference')
                             for row in mechanisms):
        blockers.add('INHERITED_EVENT_MASK_SOURCE_UNPROVEN')
    for row in mechanisms:
        reasons.add('MECHANISM_REASON:' + str(row.get('reason', 'UNKNOWN')))
    blockers.update('INDEPENDENT_QUALITY:' + flag for flag in flags)
    letter = ('E' if terminal_here else 'C' if identity_bad else 'B' if raw_bad else
              'D' if blockers else 'A')
    return dict(key=dict(ticker=ticker, date=record['date']), classification=letter,
                classification_name=CLASSES[letter], masked=record['masked'],
                clear_inherited_event_mask=letter == 'A',
                reason_flags=sorted(reasons | blockers), blocking_flags=sorted(blockers),
                mechanisms=mechanisms, evidence=record)


def classify_population(records):
    decisions = [classify_quote_key(row) for row in records]
    keys = [(v['key']['ticker'], v['key']['date']) for v in decisions]
    if len(keys) != len(set(keys)):
        raise ValueError('QUOTE_DOMAIN_DUPLICATE_POPULATION_KEY')
    return sorted(decisions, key=lambda v: (v['key']['date'], v['key']['ticker']))


def apply_quote_domain(base_quality, inherited_event_mask, dates, tickers, decisions):
    """Clear A's inherited component; never clear an independent/base quality bit.

    Population keys outside the runtime market remain fully classified evidence;
    they have no runtime cell and are counted rather than silently dropped.
    Accounting unsupported records are intentionally neither accepted nor removed.
    """
    base = np.asarray(base_quality); inherited = np.asarray(inherited_event_mask)
    if base.dtype != np.dtype(bool) or inherited.dtype != np.dtype(bool) or base.shape != inherited.shape:
        raise ValueError('QUOTE_DOMAIN_SEPARATE_BOOLEAN_MASKS_REQUIRED')
    date_keys = [str(x)[:10] for x in dates]; ticker_keys = [str(x) for x in tickers]
    if base.shape != (len(date_keys), len(ticker_keys)) or len(set(date_keys)) != len(date_keys) or len(set(ticker_keys)) != len(ticker_keys):
        raise ValueError('QUOTE_DOMAIN_RUNTIME_KEYS_NOT_UNIQUE')
    di = {v: i for i, v in enumerate(date_keys)}; ti = {v: i for i, v in enumerate(ticker_keys)}
    retained = inherited.copy(); seen = set(); cleared = []; outside = []; absent = []; counts = Counter()
    for decision in decisions:
        expected = classify_quote_key(decision['evidence'])
        if decision != expected:
            raise ValueError('QUOTE_DOMAIN_DECISION_NOT_DERIVED_FROM_EVIDENCE')
        key = (decision['key']['ticker'], decision['key']['date'])
        if key in seen:
            raise ValueError('QUOTE_DOMAIN_DUPLICATE_POPULATION_KEY')
        seen.add(key); counts[decision['classification']] += 1
        if key[0] not in ti or key[1] not in di:
            outside.append(dict(ticker=key[0], date=key[1])); continue
        ij = (di[key[1]], ti[key[0]])
        if decision['masked'] and not bool(inherited[ij]):
            absent.append(dict(ticker=key[0], date=key[1])); continue
        if decision['clear_inherited_event_mask']:
            retained[ij] = False; cleared.append(dict(ticker=key[0], date=key[1]))
    quality = base | retained
    if np.any(base & ~quality):
        raise AssertionError('QUOTE_DOMAIN_INDEPENDENT_QUALITY_REMOVED')
    return quality, dict(task_id=TASK_ID, population_keys=len(seen), classes=dict(counts),
                         cleared_inherited_keys=cleared, outside_runtime_keys=outside, already_absent_inherited_keys=absent,
                         independent_quality_preserved=True, accounting_records_changed=False,
                         terminal_lifecycle_changed=False, nav_comparator_changed=False,
                         returns_used=False)
NAMESPACE = 'FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN'
RULE_DEFINITION = {
    'window': ['2023-01-01', '2026-01-01'],
    'population': 'ALL_ORIGINAL_UNSUPPORTED_EVENT_MASK_KEYS_AGGREGATED_TICKER_DATE_WITH_ALL_SOURCE_FINGERPRINTS',
    'A_requires': ['exactly_one_raw_ticker_date_row', 'finite_positive_open_and_close',
                   'unique_dated_sid_raw_actual_share_binding', 'unique_same_day_code_ticker_binding',
                   'proven_inherited_event_mask_only', 'no_independent_quality_reason',
                   'no_terminal_or_nontradable_contract'],
    'class_names': CLASSES,
    'terminal_priority': True,
    'cash_legality_implies_quote_admission': False,
    'independent_base_quality_may_clear': False,
    'accounting_records_may_change': False,
    'outcome_or_holding_conditioned': False,
}


def _reference_path(ref):
    """Read custody only from canonical sources, with drive rejection before I/O."""
    import hashlib
    from pathlib import Path
    from scripts.common.storage_paths import resolve
    text = str(ref.get('path', ''))
    if len(text) >= 2 and text[1] == ':' and text[0].upper() in ('E', 'F'):
        raise ValueError('QUOTE_DOMAIN_FORBIDDEN_DRIVE')
    path = Path(text)
    if not path.is_absolute() or not isinstance(ref.get('sha256'), str) or len(ref['sha256']) != 64:
        raise ValueError('QUOTE_DOMAIN_ABSOLUTE_PHYSICAL_REFERENCE_REQUIRED')
    path = path.resolve(); roots = resolve(Path(__file__).resolve().parents[4])
    if not any(path.is_relative_to(p.resolve()) for p in
               (roots.repo_root, roots.results_root, roots.backtest_root, roots.data_root, roots.cache_root)):
        raise ValueError('QUOTE_DOMAIN_REFERENCE_OUTSIDE_CANONICAL_ROOTS')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != ref['sha256']:
        raise ValueError('QUOTE_DOMAIN_PHYSICAL_SOURCE_CHANGED')
    return path


def load_frozen_domain(ref):
    """Validate the committed rule/population/source custody; decode no account.

    The consumer passes a physical ref, never a caller-admission boolean. The
    population was computed before its account attempt and must still reproduce
    every decision using the same pure source rule. Source Parquet is inspected
    for clock metadata only; neither prices nor account data are decoded here.
    """
    import json
    from pathlib import Path
    frozen = json.loads(_reference_path(ref).read_text(encoding='utf-8'))
    if (frozen.get('schema') != 'FROZEN_RESEARCH_QUOTE_DOMAIN_R1' or
            frozen.get('status') != 'FROZEN_BEFORE_ACCOUNT_ATTEMPT' or
            frozen.get('task_id') != TASK_ID or frozen.get('namespace') != NAMESPACE or
            frozen.get('rule_definition') != RULE_DEFINITION or
            frozen.get('strict_PIT_promotion_eligible') is not False or
            frozen.get('production_qualified') is not False or
            frozen.get('certified_market_data') is not False or
            frozen.get('certified_market_quote_authority') is not False):
        raise ValueError('QUOTE_DOMAIN_FREEZE_IDENTITY_OR_RULE_CHANGED')
    module = _reference_path(frozen['module_ref'])
    if module != Path(__file__).resolve():
        raise ValueError('QUOTE_DOMAIN_RULE_MODULE_NOT_EXACT')
    sources = frozen.get('source_refs', {})
    required = {'raw_quotes', 'event_mechanism_source', 'security_mapping',
                'cash_catalogue', 'human_authorization', 'raw_quote_coordinate_proof'}
    if not required.issubset(sources):
        raise ValueError('QUOTE_DOMAIN_SOURCE_CUSTODY_INCOMPLETE')
    for role, source in sources.items():
        path = _reference_path(source)
        if role in ('raw_quotes', 'event_mechanism_source'):
            import pyarrow.parquet as pq
            import pandas as pd
            file = pq.ParquetFile(path); names = file.schema_arrow.names
            clock = source.get('clock_column')
            if clock not in names:
                raise ValueError('QUOTE_DOMAIN_SOURCE_CLOCK_REQUIRED')
            for i in range(file.metadata.num_row_groups):
                stats = file.metadata.row_group(i).column(names.index(clock)).statistics
                if not stats or not stats.has_min_max or pd.Timestamp(stats.max) >= pd.Timestamp('2026-01-01'):
                    raise ValueError('QUOTE_DOMAIN_SOURCE_NOT_PHYSICALLY_PRE2026')
    for path, pin in frozen.get('source_pins', {}).items():
        _reference_path(dict(path=path, sha256=pin))
    population = json.loads(_reference_path(frozen['population_ref']).read_text(encoding='utf-8'))
    decisions = population.get('decisions')
    if (population.get('schema') != 'QUOTE_MASK_POPULATION_CENSUS_R1' or
            population.get('task_id') != TASK_ID or population.get('source_refs') != sources or
            not isinstance(decisions, list) or not decisions or
            any(x.get('masked') is not True for x in decisions)):
        raise ValueError('QUOTE_DOMAIN_POPULATION_IDENTITY_CHANGED')
    rebuilt = classify_population([x['evidence'] for x in decisions])
    if rebuilt != decisions or population.get('masked_key_count') != len(rebuilt):
        raise ValueError('QUOTE_DOMAIN_POPULATION_NOT_DERIVED_FROM_SOURCE_RULE')
    return dict(frozen, decisions=decisions)