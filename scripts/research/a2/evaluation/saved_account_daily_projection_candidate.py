"""Inactive, consumer-specific four-column projection of the frozen daily reader.

This factory does not install itself or alter any frozen source. Only the named
recovery consumer uses the four returned columns; this is not a general reader.
"""
from pathlib import Path
import ast
import copy
import hashlib
import inspect
import textwrap

READER_SHA = 'be6825997eadb46ee2b0c5f389a83307808a7b28d79669ca5188dfafa180a83a'
CONSUMER_SHA = '99a6c44cdba9c23a44abad0eb470152bdd15982af39fe7416f478d14d138a0ae'
COLUMNS = ('date', 'TOTAL_ECONOMIC_NAV', 'cash', 'receivable_value_usd')

def build_consumer_daily_reader(original_daily_for, consumer_path):
    """Change only read_table's output projection; retain every original check."""
    reader_path = Path(inspect.getsourcefile(original_daily_for))
    consumer_path = Path(consumer_path)
    if hashlib.sha256(reader_path.read_bytes()).hexdigest() != READER_SHA:
        raise ValueError('FROZEN_DAILY_READER_CHANGED')
    if hashlib.sha256(consumer_path.read_bytes()).hexdigest() != CONSUMER_SHA:
        raise ValueError('CONSUMER_SCOPE_CHANGED')
    tree = ast.parse(textwrap.dedent(inspect.getsource(original_daily_for)))
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != 'daily_for':
        raise ValueError('EXACT_DAILY_FUNCTION_REQUIRED')
    before = ast.dump(tree, include_attributes=False)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == 'pq' and n.func.attr == 'read_table']
    if len(calls) != 1:
        raise ValueError('EXACT_ONE_TABLE_READ_REQUIRED')
    fields = [k for k in calls[0].keywords if k.arg == 'columns']
    if len(fields) != 1 or ast.dump(fields[0].value) != ast.dump(ast.Name(id='names', ctx=ast.Load())):
        raise ValueError('ORIGINAL_COLUMN_PROJECTION_CHANGED')
    old = copy.deepcopy(fields[0].value)
    fields[0].value = ast.List(elts=[ast.Constant(x) for x in COLUMNS], ctx=ast.Load())
    after = ast.dump(tree, include_attributes=False)
    fields[0].value, changed = old, fields[0].value
    if ast.dump(tree, include_attributes=False) != before:
        raise ValueError('NON_PROJECTION_CHANGE')
    fields[0].value = changed
    namespace = dict(original_daily_for.__globals__)
    exec(compile(ast.fix_missing_locations(tree), str(Path(__file__)), 'exec'), namespace)
    proof = {'original_reader_sha256': READER_SHA, 'original_consumer_sha256': CONSUMER_SHA,
             'original_function_ast_sha256': hashlib.sha256(before.encode()).hexdigest(),
             'candidate_function_ast_sha256': hashlib.sha256(after.encode()).hexdigest(),
             'only_change': 'pq.read_table output columns: six to consumer-required four',
             'original_six_column_schema_gate_preserved': True,
             'filters_sort_and_all_checks_preserved': True, 'reverse_ast_equals_original': True,
             'output_columns': list(COLUMNS), 'installed_into_active_pipeline': False}
    return namespace['daily_for'], proof
