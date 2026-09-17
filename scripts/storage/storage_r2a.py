"""R2A storage contract helpers; intentionally offline and broker-free."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

# Keep script entrypoints working without mutating sys.path or duplicating routing.
_resolver_spec = importlib.util.spec_from_file_location(
    "_ustq_storage_root_resolver", Path(__file__).resolve().parents[1] / "common/storage_paths.py"
)
if _resolver_spec is None or _resolver_spec.loader is None:
    raise ImportError("canonical storage root resolver is unavailable")
_resolver = importlib.util.module_from_spec(_resolver_spec)
sys.modules[_resolver_spec.name] = _resolver
_resolver_spec.loader.exec_module(_resolver)
StoragePaths = _resolver.StoragePaths
resolve_storage_paths = _resolver.resolve
_PATHS = resolve_storage_paths()
REPO_ROOT, DATA_ROOT = _PATHS.repo_root, _PATHS.data_root
BACKTEST_ROOT, DAILY_ROOT, CACHE_ROOT = _PATHS.backtest_root, _PATHS.daily_root, _PATHS.cache_root
ALLOWED_ROOTS = tuple(getattr(_PATHS, key) for key in _resolver.DEFAULTS)
MAX_REPO_FILE_BYTES = 20 * 1024 * 1024
CATALOG_SCHEMA_VERSION = "1"
CATALOG_ROLE = "REBUILDABLE_FILE_INDEX"
CATALOG_FIELDS = frozenset({
    "dataset", "ticker", "adjustment", "path", "format", "source", "source_sha256",
    "vintage_id", "row_count", "min_date", "max_date", "updated_utc", "lineage_json", "is_current",
})
DAILY_PRICE_FIELDS = frozenset({
    "ticker", "date", "open", "high", "low", "close", "volume", "turnover",
    "adjustment", "source", "provider_code", "source_id", "observed_at",
})
DAILY_PRICE_CONTRACTS = {
    "prices_daily": {"sources": ("MOOMOO_OPEND", "MOOMOO"), "adjustments": ("raw", "qfq"),
                     "required_fields": DAILY_PRICE_FIELDS},
    "prices_daily_yahoo": {"sources": ("YAHOO_CHART",), "adjustments": ("split_adjusted",),
                           "required_fields": DAILY_PRICE_FIELDS | {"adjusted_close"},
                           "price_basis": "SPLIT_ADJUSTED", "label": "Yahoo", "retrieval_prefix": "YAHOO"},
    "prices_daily_massive": {"sources": ("MASSIVE_GROUPED",), "adjustments": ("raw",),
                             "required_fields": DAILY_PRICE_FIELDS,
                             "price_basis": "RAW", "label": "Massive", "retrieval_prefix": "MASSIVE"},
}
DAILY_PROVIDER_DATASETS = {"moomoo": "prices_daily", "yahoo": "prices_daily_yahoo", "massive": "prices_daily_massive"}
CATALOG_SCHEMA_SQL = """
CREATE TABLE catalog_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE data_files (
    dataset TEXT NOT NULL, ticker TEXT NOT NULL DEFAULT '',
    adjustment TEXT NOT NULL DEFAULT '', path TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'parquet', source TEXT, source_sha256 TEXT,
    vintage_id TEXT, row_count INTEGER, min_date TEXT, max_date TEXT,
    updated_utc TEXT, lineage_json TEXT NOT NULL DEFAULT '{}',
    is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
    PRIMARY KEY (dataset, ticker, adjustment, path)
);
CREATE UNIQUE INDEX one_current_data_file ON data_files(dataset, ticker, adjustment)
WHERE is_current = 1;
"""


def validate_daily_price_metadata(row: dict, lineage: dict) -> dict | None:
    """Validate explicit provider/basis metadata, without reading price payloads."""
    dataset = row["dataset"]
    if isinstance(lineage, dict) and "inputs_manifest" in lineage:
        if dataset != "prices_daily_massive":
            raise ValueError("shared raw-input manifests are only supported for Massive daily prices")
        reference = lineage["inputs_manifest"]
        if "inputs" in lineage:
            raise ValueError("inline inputs and inputs_manifest are mutually exclusive")
        if not isinstance(reference, dict) or not {"path", "sha256"}.issubset(reference) or set(reference) - {"path", "sha256", "indexes"}:
            raise ValueError("invalid shared raw-input manifest reference")
        if "indexes" in reference:
            indexes = reference["indexes"]
            if (not isinstance(indexes, list) or not indexes or any(type(index) is not int or index < 0 for index in indexes)
                    or indexes != sorted(set(indexes))):
                raise ValueError("manifest indexes must be nonempty, sorted unique nonnegative integers")
    contract = DAILY_PRICE_CONTRACTS.get(dataset)
    if contract is None:
        if dataset.startswith("prices_daily_"):
            raise ValueError("unsupported daily price dataset contract")
        return None
    if dataset == "prices_daily":
        return contract  # Preserve the established legacy metadata contract.
    label = contract["label"]
    expected = {"schema_version": 1, "role": "PROVIDER_DAILY_PRICE_SNAPSHOT", "provider": contract["sources"][0],
                "date_column": "date", "price_basis": contract["price_basis"], "currency": "USD",
                "exchange_timezone": "America/New_York", "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT"}
    if not isinstance(lineage, dict) or any(lineage.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{label} daily lineage schema/source/price-basis/currency/timezone/vintage contract mismatch")
    if row.get("format") != "parquet" or row.get("source") not in contract["sources"] or row.get("adjustment") not in contract["adjustments"]:
        raise ValueError(f"{label} daily catalog source/adjustment/format contract mismatch")
    symbol = lineage.get("provider_symbol")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=/_-]{0,63}", symbol) or ".." in symbol:
        raise ValueError(f"{label} daily lineage requires the explicit returned provider_symbol")
    if "inputs_manifest" not in lineage and (not isinstance(lineage.get("inputs"), list) or not lineage["inputs"]):
        raise ValueError(f"{label} daily lineage requires source inputs")
    return contract


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def assert_allowed(path: Path) -> None:
    if not any(is_under(path, root) for root in ALLOWED_ROOTS):
        raise ValueError(f"FAIL_STORAGE_CONTRACT_VIOLATION: path outside allowed roots: {path}")


def assert_write_path(path: Path, purpose: str) -> None:
    assert_allowed(path)
    resolved = path.resolve()
    if is_under(resolved, REPO_ROOT):
        rel = resolved.relative_to(REPO_ROOT.resolve())
        if rel.parts and rel.parts[0].lower() in {"outputs", "exports"}:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: repo outputs/exports are prohibited")
        if path.suffix.lower() in {".csv", ".parquet", ".zip"}:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: large data format prohibited in repo")
    if purpose == "market_data" and not is_under(resolved, DATA_ROOT / "stocks"):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: market data must be under data_root/stocks")
    if purpose == "daily" and not is_under(resolved, DAILY_ROOT):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: daily output must be under daily_root")
    if purpose == "backtest" and not is_under(resolved, BACKTEST_ROOT):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: backtest output must be under backtest_root")
    if purpose == "derived" and not (is_under(resolved, CACHE_ROOT / "derived") or is_under(resolved, BACKTEST_ROOT)):
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: derived output must be cache/derived or a backtest run")


def assert_safety_flags(payload: dict) -> None:
    if payload.get("broker_action_allowed", False) is not False or payload.get("official_adoption_allowed", False) is not False or payload.get("research_only", True) is not True:
        raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: research safety flags changed")


def write_json_atomic(path: Path, payload: dict) -> None:
    assert_write_path(path, "state" if is_under(path, REPO_ROOT / "state") else "backtest")
    assert_safety_flags(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def storage_guard_result(path: Path, purpose: str, run_id: str = "") -> dict:
    try:
        if purpose == "backtest" and not run_id:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: backtest run_id is required")
        assert_write_path(path, purpose)
        if is_under(path, REPO_ROOT) and path.exists() and path.stat().st_size > MAX_REPO_FILE_BYTES:
            raise ValueError("FAIL_STORAGE_CONTRACT_VIOLATION: repo file exceeds 20 MB")
        return {"path": str(path), "purpose": purpose, "run_id": run_id, "result": "PASS"}
    except Exception as exc:
        return {"path": str(path), "purpose": purpose, "run_id": run_id, "result": "FAIL", "reason": str(exc)}


def load_ticker_daily(ticker: str, adjustment: str, start_date: str | None = None, end_date: str | None = None):
    return DataStore().daily(ticker, adjustment, start_date, end_date)


def load_ticker_intraday(ticker: str, timeframe: str, start_time: str | None = None, end_time: str | None = None):
    import pandas as pd
    store = DataStore()
    ticker = store._ticker(ticker, single_component=True)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", timeframe):
        raise ValueError("invalid intraday timeframe")
    folder = store.paths.data_root / "stocks" / ticker / "intraday" / timeframe
    store._check_data_path(folder, must_exist=False)
    files = sorted(folder.glob("*.parquet"))
    frames = [store._read_parquet(p, start_time, end_time, None, "datetime", ticker) for p in files]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return frame.sort_values("datetime").reset_index(drop=True) if not frame.empty else frame


def scan_universe_daily(tickers: Iterable[str], adjustment: str, start_date: str | None = None, end_date: str | None = None):
    import pandas as pd
    frames = [load_ticker_daily(ticker, adjustment, start_date, end_date) for ticker in tickers]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


class DataStore:
    """Read existing Parquet through an optional, rebuildable file catalog.

    The catalog records file selection, coverage and lineage, not security identity
    or research acceptance. Current means selected by the catalog builder; it does
    not imply complete history, PIT eligibility or promotion. Use immutable source
    manifests and vintage IDs to reproduce a research input. No writes or network
    requests are performed by this interface.
    """

    def __init__(self, storage_paths: StoragePaths | None = None, catalog_path: str | Path | None = None):
        self.paths = storage_paths or resolve_storage_paths()
        _resolver.validate(self.paths)
        # Keep the existing configuration contract and pin its allowed targets
        # for this reader. Every accessed data path still resolves afresh.
        self._data_roots = tuple(Path(getattr(self.paths, key)).resolve() for key in (
            "data_root", "cache_root", "daily_root", "backtest_root", "results_root"
        ))
        self.catalog_path = Path(catalog_path) if catalog_path is not None else (
            self.paths.cache_root / "derived/data_catalog/catalog.sqlite3"
        )
        self._check_data_path(self.catalog_path, must_exist=False)

    @staticmethod
    def _ticker(value: str, single_component: bool = False) -> str:
        ticker = str(value).strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,63}", ticker) or ".." in ticker:
            raise ValueError("invalid ticker")
        if single_component and "/" in ticker:
            raise ValueError("ticker requires a catalog mapping; legacy path must be a single component")
        return ticker

    @staticmethod
    def _adjustment(value: str) -> str:
        adjustment = str(value).lower()
        if adjustment not in {"raw", "qfq"}:
            raise ValueError("adjustment must be raw or qfq")
        return adjustment

    def _check_data_path(self, path: Path, must_exist: bool = True) -> Path:
        path = path.resolve()
        if not any(path.is_relative_to(root) for root in self._data_roots):
            raise ValueError(f"data path outside configured data/artifact roots: {path}")
        if must_exist and not path.exists():
            raise FileNotFoundError(f"selected data file is missing: {path}")
        return path

    def _catalog_rows(self, dataset: str, ticker: str | None = None, adjustment: str | None = None) -> list[dict]:
        self._check_data_path(self.catalog_path)
        try:
            with sqlite3.connect(self.catalog_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
                connection.row_factory = sqlite3.Row
                metadata = dict(connection.execute("SELECT key, value FROM catalog_metadata"))
                if metadata.get("schema_version") != CATALOG_SCHEMA_VERSION:
                    raise ValueError("unsupported or missing catalog schema_version")
                if metadata.get("catalog_role") != CATALOG_ROLE:
                    raise ValueError("catalog_role must be REBUILDABLE_FILE_INDEX")
                fields = {row["name"] for row in connection.execute("PRAGMA table_info(data_files)")}
                if not CATALOG_FIELDS.issubset(fields):
                    raise ValueError("invalid catalog data_files schema: required columns are missing")
                where, params = ["dataset = ?", "is_current = 1"], [dataset]
                for key, value in (("ticker", ticker), ("adjustment", adjustment)):
                    if value is not None:
                        where.append(f"{key} = ?")
                        params.append(value)
                rows = [dict(row) for row in connection.execute(
                    "SELECT * FROM data_files WHERE " + " AND ".join(where) + " ORDER BY ticker, adjustment, path", params
                )]
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"invalid data catalog: {exc}") from exc
        keys = [(row["dataset"], row["ticker"], row["adjustment"]) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("ambiguous catalog: multiple current files for the same dataset/ticker/adjustment")
        return rows

    def resolve_price_inputs(self, row: dict, *, verify_raw: bool = True) -> list[dict]:
        """Resolve exact row-source inputs without expanding the persisted catalog.

        Shared manifests are Massive-only, immutable, nonrecursive leaf lists.
        With verify_raw=False, only the manifest bytes/schema and leaf path bounds
        are verified; raw bytes are not checked. Full validation uses its per-run
        raw hash cache. Explicit verify_raw=True checks the selected raw files.
        """
        lineage = row.get("lineage", None)
        if lineage is None:
            lineage = json.loads(row.get("lineage_json") or "{}")
        if not isinstance(lineage, dict):
            raise ValueError("lineage must be an object")
        validate_daily_price_metadata(row, lineage)

        def checked_path(value, digest, *, must_exist):
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError("raw-input paths must be absolute")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid raw-input SHA-256")
            path = self._check_data_path(Path(value), must_exist=must_exist)
            if must_exist and not path.is_file():
                raise ValueError("raw-input path must name a regular file")
            return path

        reference = lineage.get("inputs_manifest")
        if reference is None:
            inputs = lineage.get("inputs", [])
            if not isinstance(inputs, list) or any(not isinstance(item, dict) for item in inputs):
                raise ValueError("lineage inputs must be a list of objects")
        else:
            manifest_path = checked_path(reference["path"], reference["sha256"], must_exist=True)
            content = manifest_path.read_bytes()
            if hashlib.sha256(content).hexdigest() != reference["sha256"]:
                raise ValueError("shared raw-input manifest SHA-256 mismatch")
            manifest = json.loads(content)
            if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "role", "provider", "inputs"}
                    or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
                    or manifest.get("role") != "RAW_INPUT_MANIFEST" or manifest.get("provider") != "MASSIVE_GROUPED"
                    or not isinstance(manifest.get("inputs"), list) or not manifest["inputs"]):
                raise ValueError("invalid shared raw-input manifest schema/provider/role")
            paths, digests, dates = set(), set(), []
            for item in manifest["inputs"]:
                if not isinstance(item, dict) or set(item) != {"path", "sha256", "date", "observed_at"}:
                    raise ValueError("shared raw-input manifest requires leaf inputs; nesting is forbidden")
                path = checked_path(item["path"], item["sha256"], must_exist=False)
                if path == manifest_path:
                    raise ValueError("shared raw-input manifest cannot reference itself")
                value = item["date"]
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("raw-input date must be an ISO calendar date")
                date.fromisoformat(value)
                observed = item["observed_at"]
                if not isinstance(observed, str) or "T" not in observed:
                    raise ValueError("raw-input observed_at requires an explicit timezone")
                stamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValueError("raw-input observed_at requires an explicit timezone")
                path_key = os.path.normcase(str(path))
                if path_key in paths or item["sha256"] in digests or value in dates:
                    raise ValueError("duplicate path/SHA/date in shared raw-input manifest")
                paths.add(path_key); digests.add(item["sha256"]); dates.append(value)
            if dates != sorted(dates):
                raise ValueError("shared raw-input manifest dates must be sorted")
            indexes = reference.get("indexes", list(range(len(manifest["inputs"]))))
            if any(index >= len(manifest["inputs"]) for index in indexes):
                raise ValueError("shared raw-input manifest index out of bounds")
            inputs = [manifest["inputs"][index] for index in indexes]
            if sha256(manifest_path) != reference["sha256"]:
                raise ValueError("shared raw-input manifest changed during resolution")
        if verify_raw:
            for item in inputs:
                path = checked_path(item.get("path"), item.get("sha256"), must_exist=True)
                if sha256(path) != item["sha256"]:
                    raise ValueError("raw-input file SHA-256 mismatch")
        return inputs

    def metadata(self, dataset: str, ticker: str = "", adjustment: str = "") -> dict:
        ticker = self._ticker(ticker) if ticker else ""
        if self.catalog_path.exists():
            rows = self._catalog_rows(dataset, ticker, adjustment)
            if not rows:
                raise KeyError(f"no current catalog entry for {dataset}/{ticker}/{adjustment}")
            row = rows[0]
            if row.get("format") not in {"parquet", "parquet_manifest"}:
                raise ValueError("DataStore only reads Parquet or an explicit Parquet manifest")
            if not Path(row["path"]).is_absolute():
                raise ValueError("catalog paths must be absolute")
            row["path"] = str(self._check_data_path(Path(row["path"])))
            row["lineage"] = json.loads(row.get("lineage_json") or "{}")
            validate_daily_price_metadata(row, row["lineage"])
            if "inputs_manifest" in row["lineage"]:
                self.resolve_price_inputs(row, verify_raw=False)
            row["selection_source"] = "catalog_current"
            return row
        if dataset != "prices_daily":
            raise FileNotFoundError(f"catalog is required for dataset {dataset}: {self.catalog_path}")
        ticker = self._ticker(ticker, single_component=True)
        adjustment = self._adjustment(adjustment)
        folder = self.paths.data_root / "stocks" / ticker
        path = self._check_data_path(folder / f"daily_{adjustment}.parquet")
        metadata_path = folder / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        return {"dataset": dataset, "ticker": ticker, "adjustment": adjustment, "path": str(path),
                "format": "parquet", "selection_source": "legacy_per_ticker_no_catalog", "lineage": metadata}

    def list_tickers(self, dataset: str = "prices_daily", adjustment: str | None = None) -> list[str]:
        if self.catalog_path.exists():
            return sorted({row["ticker"] for row in self._catalog_rows(dataset, adjustment=adjustment) if row["ticker"]})
        if dataset != "prices_daily":
            raise FileNotFoundError(f"catalog is required for dataset {dataset}: {self.catalog_path}")
        suffix = self._adjustment(adjustment) if adjustment else "*"
        return sorted({p.parent.name for p in (self.paths.data_root / "stocks").glob(f"*/daily_{suffix}.parquet")})

    def read(self, dataset: str, ticker: str = "", adjustment: str = "", start_date: str | None = None,
             end_date: str | None = None, columns: Iterable[str] | None = None,
             date_column: str = "date", partitioning: str | None = None):
        """Read the selected file/directory with bounds applied in Arrow's scanner.

        Bounds are inclusive and filter event dates only. They do not establish
        disclosure availability or historical adjustment vintage. Financial/13F
        consumers must apply the existing accession/acceptance/PIT contract.
        Pass partitioning='hive' for a Hive-partitioned Parquet directory.
        """
        ticker = self._ticker(ticker) if ticker else ""
        row = self.metadata(dataset, ticker, adjustment)
        if row["format"] == "parquet_manifest":
            from scripts.storage.build_parquet_manifest import load_manifest, verify_hashes
            if partitioning is not None:
                raise ValueError("manifest files have an explicit schema; partitioning must be None")
            manifest, files, schema = load_manifest(self, row)
            if date_column == "date":
                date_column = manifest["date_column"]
            result = self._read_parquet(files, start_date, end_date, columns, date_column,
                                        ticker, schema=schema, ticker_column=manifest["ticker_column"])
            verify_hashes(self, row["path"], row["source_sha256"], manifest)
            return result
        if dataset in DAILY_PRICE_CONTRACTS and dataset != "prices_daily":
            shared = "inputs_manifest" in row["lineage"]
            if shared and sha256(Path(row["path"])) != row.get("source_sha256"):
                raise ValueError("selected shared-lineage price file SHA-256 mismatch")
            result = self._read_parquet(Path(row["path"]), start_date, end_date, columns, date_column, ticker,
                                        partitioning, required_fields=DAILY_PRICE_CONTRACTS[dataset]["required_fields"])
            if shared:
                self.resolve_price_inputs(row, verify_raw=False)
                if sha256(Path(row["path"])) != row.get("source_sha256"):
                    raise ValueError("selected shared-lineage price file changed during read")
            return result
        return self._read_parquet(Path(row["path"]), start_date, end_date, columns, date_column, ticker, partitioning)

    def daily(self, ticker: str, adjustment: str = "qfq", start_date: str | None = None,
              end_date: str | None = None, columns: Iterable[str] | None = None, *, provider: str = "moomoo"):
        """Read an explicitly selected provider; the existing Moomoo default never falls back."""
        key = str(provider).strip().lower()
        if key not in DAILY_PROVIDER_DATASETS:
            raise ValueError("unsupported daily price provider")
        dataset = DAILY_PROVIDER_DATASETS[key]
        adjustment = str(adjustment).lower()
        if adjustment not in DAILY_PRICE_CONTRACTS[dataset]["adjustments"]:
            raise ValueError(f"unsupported adjustment for {key}; select the provider's explicit price basis")
        return self.read(dataset, ticker, adjustment, start_date, end_date, columns)

    def _read_parquet(self, path: Path | list[Path], start_date: str | None, end_date: str | None,
                      columns: Iterable[str] | None, date_column: str, ticker: str = "", partitioning: str | None = None,
                      *, schema=None, ticker_column: str = "ticker", required_fields: Iterable[str] = ()):
        import pandas as pd
        import pyarrow as pa
        import pyarrow.dataset as ds

        source = [str(self._check_data_path(p)) for p in path] if isinstance(path, list) else str(self._check_data_path(path))
        if partitioning not in {None, "hive"}:
            raise ValueError("partitioning must be None or hive")
        dataset = ds.dataset(source, format="parquet", partitioning=partitioning, schema=schema)
        missing = set(required_fields) - set(dataset.schema.names)
        if missing:
            raise ValueError("daily price schema missing columns: " + ",".join(sorted(missing)))
        for fragment_path in dataset.files:
            self._check_data_path(Path(fragment_path))
        expression = None
        if start_date is not None and end_date is not None and pd.Timestamp(start_date) > pd.Timestamp(end_date):
            raise ValueError("start_date must not exceed end_date")
        if start_date is not None or end_date is not None:
            if date_column not in dataset.schema.names:
                raise ValueError(f"date column missing: {date_column}")
            dtype = dataset.schema.field(date_column).type
            for bound, lower in ((start_date, True), (end_date, False)):
                if bound is None:
                    continue
                stamp = pd.Timestamp(bound)
                if pd.isna(stamp):
                    raise ValueError("date boundary must be finite")
                if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
                    value = stamp.date().isoformat() if date_column == "date" else str(bound)
                elif pa.types.is_date(dtype):
                    value = stamp.date()
                elif pa.types.is_timestamp(dtype):
                    if (stamp.tzinfo is None) != (dtype.tz is None):
                        raise ValueError("date boundary timezone must match the stored timestamp")
                    value = stamp
                else:
                    raise ValueError(f"unsupported date column type: {dtype}")
                clause = ds.field(date_column) >= pa.scalar(value, type=dtype) if lower else ds.field(date_column) <= pa.scalar(value, type=dtype)
                expression = clause if expression is None else expression & clause
        if ticker:
            if ticker_column not in dataset.schema.names:
                raise ValueError("ticker column is required for ticker-scoped reads")
            clause = ds.field(ticker_column) == ticker
            expression = clause if expression is None else expression & clause
        requested = list(columns) if columns is not None else None
        selected = list(requested) if requested is not None else None
        if selected is not None and date_column in dataset.schema.names and date_column not in selected:
            selected.append(date_column)
        frame = dataset.to_table(columns=selected, filter=expression).to_pandas()
        if date_column in frame.columns:
            frame = frame.sort_values(date_column, kind="stable")
        if requested is not None:
            frame = frame[requested]
        return frame.reset_index(drop=True)
