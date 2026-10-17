"""Bounded reader memory over synthetic, task-owned evidence only."""
import ast
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from pandas.testing import assert_frame_equal
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import selected_strategies_reader as selected
from apps.demo_console.adapters import stock_history_reader as stock
from apps.demo_console.adapters import updated_research_reader as updated
from apps.demo_console.tests.test_selected_strategies_reader_workspace import package


@pytest.fixture(autouse=True)
def bounded_caches():
    selected.clear_cache()
    stock._cached_history.cache_clear()
    stock._cached_applied_history.cache_clear()
    updated.clear_cache()
    yield
    selected.clear_cache()
    stock._cached_history.cache_clear()
    stock._cached_applied_history.cache_clear()
    updated.clear_cache()


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_decode_keeps_only_latest_content_with_caller_isolation_and_utf8_bom(tmp_path):
    path = tmp_path / "package.json"
    payload = package()
    a = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    changed = deepcopy(payload)
    changed["strategies"][selected.STRATEGY_IDS[0]]["label"] += " v2"
    b = json.dumps(changed, ensure_ascii=False).encode("utf-8")
    path.write_bytes(a)
    first = selected.load_package(path)
    first["strategies"][selected.STRATEGY_IDS[0]]["label"] = "caller mutation"
    assert selected.load_package(path)["strategies"] == payload["strategies"]
    path.write_bytes(b)
    assert selected.load_package(path)["strategies"] == changed["strategies"]
    path.write_bytes(a)
    assert selected.load_package(path)["strategies"] == payload["strategies"]
    info = selected._decode.cache_info()
    assert (info.maxsize, info.currsize, info.misses) == (1, 1, 3)
    path.write_bytes(b"\xef\xbb\xbf" + a)
    assert selected.load_package(path)["strategies"] == payload["strategies"]
    path.write_bytes(json.dumps(payload).encode("utf-16"))
    with pytest.raises(UnicodeError):
        selected.load_package(path)


@pytest.mark.parametrize("raw", [b'{"key":1,"key":2}', b'{"key":NaN}', b'{"key":Infinity}'])
def test_bytes_cache_preserves_duplicate_and_nonfinite_rejection(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        selected.load_package(path)


def test_refresh_observation_hashes_content_without_decoding_or_claiming_ready(tmp_path, monkeypatch):
    path = tmp_path / "not_a_valid_package.json"
    first = b"opaque0001"
    path.write_bytes(first)
    stat = path.stat()
    monkeypatch.setattr(selected, "_decode", lambda *_: pytest.fail("refresh decoded a package"))
    assert selected.package_observation_sha256(path) == hashlib.sha256(first).hexdigest()
    second = b"opaque0002"
    path.write_bytes(second)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert selected.package_observation_sha256(path) == hashlib.sha256(second).hexdigest()
    assert selected.package_observation_sha256(path) != hashlib.sha256(first).hexdigest()
    monkeypatch.setattr(selected, "_MAX_BYTES", 4)
    with pytest.raises(ValueError, match="package_size"):
        selected.package_observation_sha256(path)


def test_arrow_frame_projects_columns_without_per_row_dicts(tmp_path, monkeypatch):
    path = tmp_path / "ranked.parquet"
    table = pa.table({"target_date": [date(2025, 1, 2), date(2025, 1, 3)],
        "ticker": ["SYN_A", "SYN_A"], "rank": [1, None], "score": [.25, -.5],
        "mapping_verified": [True, False], "unused_payload": ["x" * 100, "y" * 100]})
    pq.write_table(table, path)
    columns = ["target_date", "ticker", "rank", "score", "mapping_verified"]
    expected = pd.DataFrame(table.select(columns).to_pylist(), columns=columns)
    calls = []
    original = updated.pq.read_table
    def read(*args, **kwargs):
        calls.append(kwargs.get("columns"))
        return original(*args, **kwargs)
    monkeypatch.setattr(updated.pq, "read_table", read)
    monkeypatch.setattr(updated, "_table", lambda *_a, **_k: pytest.fail("created row dictionaries"))
    result = stock._frame(ref(path), tmp_path, columns)
    assert_frame_equal(result, expected)
    assert calls == [columns]


def test_arrow_projection_keeps_parent_columns_and_before_after_hash_guards(tmp_path, monkeypatch):
    parent = tmp_path / "owned"
    parent.mkdir()
    path = parent / "ranked.parquet"
    pq.write_table(pa.table({"ticker": ["SYN_A"], "score": [.1]}), path)
    pinned = ref(path)
    calls = []
    original = updated.pq.read_table
    def read(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(updated.pq, "read_table", read)
    with pytest.raises(ValueError, match="OUTSIDE_RUN"):
        updated._arrow_table(pinned, ["ticker"], parent=parent / "other")
    with pytest.raises(ValueError, match="COLUMNS_MISSING"):
        updated._arrow_table(pinned, ["security_id"], parent=parent)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        updated._arrow_table({**pinned, "sha256": "0" * 64}, ["ticker"], parent=parent)
    assert not calls
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_bytes(b"changed during read")
        return result
    monkeypatch.setattr(updated.pq, "read_table", changed)
    with pytest.raises(ValueError, match="CHANGED_DURING_READ"):
        updated._arrow_table(pinned, ["ticker"], parent=parent)


@pytest.mark.parametrize("with_pandas_metadata", [False, True])
def test_arrow_dictionary_and_index_metadata_keep_legacy_catalog_order(tmp_path, with_pandas_metadata):
    source = pd.DataFrame({"snapshot_id": ["s", "s"],
        "ticker": pd.Categorical(["Z_SYN", "A_SYN"],
            categories=["Z_SYN", "A_SYN", "UNUSED_SYN"]),
        "security_id": ["id-Z", "id-A"], "issuer_name": ["Z issuer", "A issuer"],
        "mapping_verified": [True, True]}, index=pd.RangeIndex(5, 7, name="synthetic_index"))
    table = pa.Table.from_pandas(source)
    if not with_pandas_metadata:
        table = table.replace_schema_metadata(None)
    path = tmp_path / "members_dictionary.parquet"
    pq.write_table(table, path)
    columns = list(source.columns)
    previous = pd.DataFrame(table.select(columns).to_pylist(), columns=columns)
    current = stock._frame(ref(path), tmp_path, columns)
    assert_frame_equal(current, previous)
    ranked = pd.DataFrame({"target_date": ["2025-01-02", "2025-01-02"],
        "ticker": ["Z_SYN", "A_SYN"], "security_id": ["id-Z", "id-A"],
        "rank": [2, 1], "score": [.1, .2], "universe_id": ["u", "u"]})
    ledger = pd.DataFrame({"target_date": ["2025-01-02"], "snapshot_id": ["s"],
        "universe_id": ["u"], "quarter": ["2024Q3"]})
    prior_history = stock.prepare_history(ranked, ledger, previous)
    current_history = stock.prepare_history(ranked, ledger, current)
    assert current_history["status"] == prior_history["status"] == "READY"
    assert current_history["catalog"] == prior_history["catalog"]
    assert [row["ticker"] for row in current_history["catalog"]] == ["A_SYN", "Z_SYN"]
    for key in ("_ranked", "_ledger", "_members"):
        assert_frame_equal(current_history[key], prior_history[key])


def history_fixture(folder, ticker):
    folder.mkdir()
    tables = {
        "ranked": pa.table({"target_date": ["2025-01-02"], "ticker": [ticker],
            "security_id": ["id-" + ticker], "rank": [1], "score": [.1], "universe_id": ["u"]}),
        "ledger": pa.table({"target_date": ["2025-01-02"], "snapshot_id": ["s"],
            "universe_id": ["u"], "quarter": ["2024Q3"]}),
        "members": pa.table({"snapshot_id": ["s"], "ticker": [ticker],
            "security_id": ["id-" + ticker], "issuer_name": [ticker], "mapping_verified": [True]})}
    refs = {}
    for name, table in tables.items():
        path = folder / (name + ".parquet")
        pq.write_table(table, path)
        refs[name] = ref(path)
    hist = folder / "history.json"
    hist.write_text(json.dumps({"outputs": {"ranked": refs["ranked"]},
        "universe_outputs": {key: refs[key] for key in ("ledger", "members")}}), encoding="utf-8")
    parent = folder / "parent.json"
    parent.write_text(json.dumps({"ranking_manifest": ref(hist)}), encoding="utf-8")
    return SimpleNamespace(reference=ref(parent)), refs["ranked"]


def test_history_cache_eviction_reloads_content_and_never_trusts_same_stamp(tmp_path, monkeypatch):
    from apps.demo_console.adapters import workspace_reader
    a, ranked_ref = history_fixture(tmp_path / "a", "SYN_A")
    b, _ = history_fixture(tmp_path / "b", "SYN_B")
    monkeypatch.setattr(workspace_reader, "source_reference", lambda m: m.reference)
    assert stock.load_history(a, include_rx=False)["catalog"][0]["ticker"] == "SYN_A"
    assert stock.load_history(a, include_rx=False)["catalog"][0]["ticker"] == "SYN_A"
    assert stock.load_history(b, include_rx=False)["catalog"][0]["ticker"] == "SYN_B"
    assert stock.load_history(a, include_rx=False)["catalog"][0]["ticker"] == "SYN_A"
    info = stock._cached_history.cache_info()
    assert (info.maxsize, info.currsize, info.misses, info.hits) == (1, 1, 3, 1)
    path = Path(ranked_ref["path"])
    stat = path.stat()
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    rejected = stock.load_history(a, include_rx=False)
    assert rejected["status"] == "UNAVAILABLE" and "SOURCE_HASH_MISMATCH" in rejected["error"]
    assert stock._cached_applied_history.cache_info().maxsize == 1
    assert updated._cached_bundle.cache_info().maxsize == 1


@pytest.mark.parametrize("observation,reruns", [("a" * 64, 0), ("b" * 64, 1), (None, 1)])
def test_manual_refresh_uses_bounded_content_observation_then_real_page_validation(observation, reruns):
    app_path = Path(__file__).parents[1] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_refresh_published_data")
    assert not function.decorator_list
    function.body = [node for node in function.body if not isinstance(node, ast.ImportFrom)]
    calls = []
    state = {"workspace_strategy": "HGB_DIAG_5", "_selected_strategy_binding_seen": "a" * 64}
    def observe():
        calls.append("observe")
        if observation is None:
            raise ValueError("bounded observation unavailable")
        return observation
    reader = SimpleNamespace(STRATEGY_IDS=selected.STRATEGY_IDS,
        package_observation_sha256=observe,
        load_package=lambda: pytest.fail("periodic refresh materialized the package"))
    namespace = {"st": SimpleNamespace(session_state=state, rerun=lambda: calls.append("rerun"),
                            sidebar=SimpleNamespace(button=lambda *args, **kwargs: True,
                                info=lambda message:None, error=lambda message:None)),
                 "tr": lambda source: source, "selected_strategies_reader": reader}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 str(app_path), "exec"), namespace)
    namespace["_refresh_published_data"]()
    assert calls.count("observe") == 1 and calls.count("rerun") == reruns
