"""R1 execution worker: frozen predict, one-account replay, seal, report.

Decisions are requested over a private Unix socket from a separate container
that has no test price or future-panel mount. No fit/update/selection occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


WORKER_DIR = Path(__file__).resolve().parent
R1 = WORKER_DIR.parent
TRAINED = Path(os.environ.get("R1_TRAINED_ROOT", str(R1 / "restricted_run_20260926_01" / "run")))
STATUS = "TWO_RUNTIME_FROZEN_TEST_WORKER_SOURCE_AND_INSPECT_PENDING"
BATCH = "a2_top20_clock_retrain_r1_20260926"
ASOF = "2026-09-25T15:34:48Z"
TRAIN_SEAL_SHA = "1607b78294b88fea5bb565b9b22c99fccf3bb1817d1cacce2b9126336263ee3d"
REVIEW_SEAL_SHA = "47224d323efed99c99e22c447e59e08bccfb76aa4cce0054874caf3abed0789c"
IMAGE_ID = "sha256:32365682bb6776c9f4e1abe936ab92bb7100696bc89576279d1a3c3fb9379bfe"
ROSTER = (
    "Raw", "HGB_DIAG_5", "HGB_FACTOR_5", "RL_C_SELECTED_20260925",
    "RL_C_SELECTED_20260926", "RL_C_SELECTED_TARGET_MEAN",
    "RL_C_ZERO_UPDATE", "HGB_CONTROL_A_DAILY_MEAN",
    "HGB_CONTROL_B_SHADOW_SET_GROSS_EQUAL_WEIGHT",
)
MODEL_KEYS = (
    ("ridge", 2026092501), ("elastic", 2026092501),
    ("logistic", 2026092501), ("hgb", 2026092501),
    ("mlp", 2026092501), ("mlp", 2026092502),
    ("q10", 2026092501), ("q50", 2026092501),
    ("q90", 2026092501),
)
SEEDS = (20260925, 20260926)
MAX_PANEL_ROWS = 200_000
MAX_PRICE_ROWS = 2_000_000
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
BAD_INPUT_NAME = re.compile(r"(^y\d*($|_)|label|target|future|forward|realized_pnl|pred_)", re.I)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _hex(value, name):
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise ValueError(f"invalid SHA256 binding: {name}")
    return value


def _under(root: Path, value: str) -> Path:
    p = Path(value).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError(f"path outside fixed root: {value}")
    return p


def _local_bound(rel: str) -> Path | None:
    prefix = "restricted_run_20260926_01/run/"
    if rel.startswith(prefix):
        return _under(TRAINED, str(TRAINED / rel[len(prefix):]))
    if rel.startswith("test_handoff/"):
        return _under(WORKER_DIR, str(WORKER_DIR / rel[len("test_handoff/"):]))
    candidate = R1 / rel
    return _under(R1, str(candidate)) if candidate.is_file() else None


def verify_frozen_manifest(path: Path, expected_sha: str) -> tuple[dict, str]:
    """No test-file access in this function."""
    _hex(expected_sha, "expected manifest")
    actual = sha(path)
    if actual != expected_sha:
        raise RuntimeError("FROZEN_MANIFEST_HASH_MISMATCH")
    m = json.loads(path.read_text(encoding="utf-8"))
    if m.get("status") != "FROZEN_TEST_BATCH" or m.get("batch") != BATCH:
        raise RuntimeError("R1_FULL_BATCH_FREEZE_REQUIRED")
    if m.get("test_asof_utc") != ASOF or tuple(m.get("roster", ())) != ROSTER:
        raise RuntimeError("R1_ASOF_OR_ROSTER_MISMATCH")
    if m.get("training_output_seal_sha256") != TRAIN_SEAL_SHA or m.get("review_output_seal_sha256") != REVIEW_SEAL_SHA:
        raise RuntimeError("R1_SEAL_REFERENCE_MISMATCH")
    if m.get("runtime_image_id") != IMAGE_ID:
        raise RuntimeError("R1_RUNTIME_IMAGE_MISMATCH")
    if (R1 / "TRAINING_OUTPUT_SEAL.json").is_file():
        if sha(R1 / "TRAINING_OUTPUT_SEAL.json") != TRAIN_SEAL_SHA or sha(R1 / "REVIEW_OUTPUT_SEAL.json") != REVIEW_SEAL_SHA:
            raise RuntimeError("R1_SEALED_OUTPUT_CHANGED")
    bound = m.get("bound_files")
    if not isinstance(bound, list) or not bound:
        raise RuntimeError("BOUND_FILE_LIST_MISSING")
    listed = set()
    for item in bound:
        rel = item["path"]
        p = _local_bound(rel)
        if rel in listed or (p is not None and (not p.is_file() or sha(p) != _hex(item["sha256"], rel))):
            raise RuntimeError(f"BOUND_FILE_MISMATCH:{rel}")
        listed.add(rel)
    required = {"test_handoff/test_worker.py", "test_handoff/logged_execution.py",
                "test_handoff/decision_service.py", "test_handoff/runtime_gate.py",
                "test_handoff/decision_bundle/IDENTITY.json",
                "restricted_run_20260926_01/run/ledger.py",
                "restricted_run_20260926_01/run/optimize_route.py",
                "restricted_run_20260926_01/run/risk_aux.py",
                "restricted_run_20260926_01/run/rl_core.py",
                "restricted_run_20260926_01/run/prepare.py",
                "restricted_run_20260926_01/run/risk_artifacts/final_pre2026.joblib",
                "restricted_run_20260926_01/run/rl_artifacts/C_normalization.npz"}
    required.update(f"restricted_run_20260926_01/run/models/{name}_{seed}.joblib" for name, seed in MODEL_KEYS)
    required.update(f"restricted_run_20260926_01/run/rl_artifacts/C_{kind}_{seed}.pt"
                    for kind in ("selected", "zero") for seed in SEEDS)
    if not required.issubset(listed):
        raise RuntimeError(f"MISSING_REQUIRED_BINDINGS:{sorted(required - listed)}")
    if any(_local_bound(rel) is None for rel in required):
        raise RuntimeError("REQUIRED_LOCAL_BOUND_FILE_UNMOUNTED")
    if sha(WORKER_DIR / "decision_bundle" / "IDENTITY.json") != _hex(m.get("decision_bundle_identity_sha256"), "decision bundle identity"):
        raise RuntimeError("DECISION_BUNDLE_IDENTITY_MISMATCH")
    source = m.get("test_source", {})
    for key in ("source_manifest_sha256", "a2_lineage_sha256", "feature_builder_sha256"):
        _hex(source.get(key), key)
    for key in ("panel", "prices"):
        obj = source.get(key, {})
        _hex(obj.get("sha256"), f"{key}.sha256")
        _hex(obj.get("schema_sha256"), f"{key}.schema_sha256")
        if not isinstance(obj.get("path"), str):
            raise RuntimeError(f"TEST_SOURCE_PATH_MISSING:{key}")
    if not isinstance(source.get("source_manifest_path"), str):
        raise RuntimeError("TEST_SOURCE_MANIFEST_PATH_MISSING")
    if not isinstance(source.get("mount_source"), str) or not source["mount_source"]:
        raise RuntimeError("TEST_SOURCE_MOUNT_IDENTITY_MISSING")
    if not isinstance(m.get("r1_host_root"), str) or not m["r1_host_root"]:
        raise RuntimeError("R1_HOST_ROOT_BINDING_MISSING")
    if not isinstance(m.get("approved_out_source"), str) or not m["approved_out_source"]:
        raise RuntimeError("PRIVATE_OUTPUT_MOUNT_BINDING_MISSING")
    sig = pd.Timestamp(source["last_completed_signal_session"])
    opn = pd.Timestamp(source["last_available_execution_open"])
    asof = pd.Timestamp(ASOF)
    observed = pd.Timestamp(source["open_observed_at_utc"])
    if sig.tzinfo is not None or opn.tzinfo is not None or observed.tzinfo is None:
        raise RuntimeError("SOURCE_CLOCK_FORMAT")
    et = asof.tz_convert("America/New_York")
    if not (pd.Timestamp("2026-01-01") <= sig <= opn <= pd.Timestamp(et.date())):
        raise RuntimeError("SOURCE_SESSION_WINDOW")
    if et.hour < 16 and sig >= pd.Timestamp(et.date()):
        raise RuntimeError("INCOMPLETE_SIGNAL_SESSION")
    if observed > asof or pd.Timestamp(observed.tz_convert("America/New_York").date()) != opn:
        raise RuntimeError("EXECUTION_OPEN_NOT_ASOF_AVAILABLE")
    return m, actual


def _test_path(value: str) -> Path:
    # Independent worker mount; never allow R1 source roots or user profile.
    return _under(Path("/test"), value)


def _schema_sha(source: pq.ParquetFile) -> str:
    schema = source.schema_arrow.remove_metadata()
    return hashlib.sha256(str(schema).encode("utf-8")).hexdigest()


def inspect_test_source(m: dict, *, panel_only: bool = False) -> tuple[pq.ParquetFile, pq.ParquetFile | None]:
    """Call only after verify_frozen_manifest; metadata and hashes precede values."""
    spec = m["test_source"]
    identity = _test_path(spec["source_manifest_path"])
    if sha(identity) != spec["source_manifest_sha256"]:
        raise RuntimeError("SOURCE_IDENTITY_MANIFEST_CHANGED")
    described = json.loads(identity.read_text(encoding="utf-8"))
    for key in ("batch", "test_asof_utc", "a2_lineage_sha256",
                "feature_builder_sha256", "last_completed_signal_session",
                "last_available_execution_open", "open_observed_at_utc"):
        expected = BATCH if key == "batch" else ASOF if key == "test_asof_utc" else spec[key]
        if described.get(key) != expected:
            raise RuntimeError(f"SOURCE_IDENTITY_CONTENT_MISMATCH:{key}")
    for key in ("panel", "prices"):
        if described.get(key) != spec[key]:
            raise RuntimeError(f"SOURCE_IDENTITY_CONTENT_MISMATCH:{key}")
    sources = {}
    descriptions = (
        ("panel", "signal_date", pd.Timestamp(spec["last_completed_signal_session"])),
        ("prices", "trade_date", pd.Timestamp(spec["last_available_execution_open"])),
    )
    for name, date_col, upper in descriptions[:1] if panel_only else descriptions:
        obj = spec[name]
        p = _test_path(obj["path"])
        if sha(p) != obj["sha256"]:
            raise RuntimeError(f"TEST_SOURCE_HASH_CHANGED:{name}")
        pf = pq.ParquetFile(p)
        if _schema_sha(pf) != obj["schema_sha256"]:
            raise RuntimeError(f"TEST_SOURCE_SCHEMA_CHANGED:{name}")
        columns = set(pf.schema_arrow.names)
        if any(BAD_INPUT_NAME.search(c) for c in columns):
            raise RuntimeError(f"LABEL_OR_PREDICTION_IN_TEST_SOURCE:{name}")
        if date_col not in columns:
            raise RuntimeError(f"TEST_SOURCE_DATE_MISSING:{name}")
        idx = pf.schema_arrow.names.index(date_col)
        for i in range(pf.metadata.num_row_groups):
            stats = pf.metadata.row_group(i).column(idx).statistics
            if stats is None or not stats.has_min_max:
                raise RuntimeError(f"UNPROVEN_TEST_ROW_GROUP:{name}:{i}")
            if pd.Timestamp(stats.min) < pd.Timestamp("2026-01-01") or pd.Timestamp(stats.max) > upper:
                raise RuntimeError(f"TEST_ROW_GROUP_OUT_OF_WINDOW:{name}:{i}")
        sources[name] = pf
    return sources["panel"], sources.get("prices")


def read_panel_projection(m: dict, panel_file: pq.ParquetFile, features):
    needed = ["signal_date", "ticker", "security_id", "raw_rank", *features]
    if not set(needed).issubset(panel_file.schema_arrow.names):
        raise RuntimeError("TEST_PANEL_FEATURE_SCHEMA")
    frames, total = [], 0
    for batch in panel_file.iter_batches(batch_size=16_384, columns=needed):
        total += batch.num_rows
        if total > MAX_PANEL_ROWS:
            raise MemoryError("TEST_PANEL_ROW_CAP")
        frames.append(batch.to_pandas())
    if not frames:
        raise RuntimeError("EMPTY_TEST_PANEL")
    panel = pd.concat(frames, ignore_index=True)
    del frames
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    if panel.signal_date.min() < pd.Timestamp("2026-01-01") or panel.signal_date.max() > pd.Timestamp(m["test_source"]["last_completed_signal_session"]):
        raise RuntimeError("TEST_SIGNAL_DATE_BOUNDARY")
    if panel.duplicated(["signal_date", "ticker"]).any() or panel.ticker.isna().any() or panel.security_id.isna().any():
        raise RuntimeError("TEST_PANEL_IDENTITY")
    if panel.groupby("ticker").security_id.nunique().gt(1).any():
        raise RuntimeError("TICKER_SECURITY_ID_COLLISION")
    if panel.groupby("security_id").ticker.nunique().gt(1).any():
        raise RuntimeError("SECURITY_ID_TICKER_COLLISION")
    if not all(set(g.raw_rank.to_numpy()) == set(range(1, 41)) for _, g in panel.groupby("signal_date")):
        raise RuntimeError("TEST_RAW_TOP40_RANKS")
    x = panel[features].to_numpy(float)
    if np.isinf(x).any():
        raise RuntimeError("INFINITE_TEST_FEATURE")
    return panel


def read_prices_projection(m: dict, price_file: pq.ParquetFile, panel: pd.DataFrame):
    names = set(panel.ticker.astype(str)) | {"QQQ"}
    if not {"trade_date", "ticker", "open", "close"}.issubset(price_file.schema_arrow.names):
        raise RuntimeError("TEST_PRICE_SCHEMA")
    price_frames, selected = [], 0
    for batch in price_file.iter_batches(batch_size=65_536, columns=["trade_date", "ticker", "open", "close"]):
        chunk = batch.to_pandas()
        chunk = chunk.loc[chunk.ticker.isin(names)]
        selected += len(chunk)
        if selected > MAX_PRICE_ROWS:
            raise MemoryError("TEST_SELECTED_PRICE_ROW_CAP")
        if not chunk.empty:
            price_frames.append(chunk)
    if not price_frames:
        raise RuntimeError("EMPTY_TEST_PRICES")
    prices = pd.concat(price_frames, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    if prices.duplicated(["trade_date", "ticker"]).any() or prices.trade_date.max() > pd.Timestamp(m["test_source"]["last_available_execution_open"]):
        raise RuntimeError("TEST_PRICE_DATE_OR_KEY")
    future_close = prices.loc[prices.trade_date.gt(pd.Timestamp(m["test_source"]["last_completed_signal_session"])), "close"]
    if future_close.notna().any():
        raise RuntimeError("INCOMPLETE_SESSION_CLOSE_IN_SOURCE")
    if (prices.ticker.eq("QQQ") & prices.trade_date.eq(pd.Timestamp(m["test_source"]["last_available_execution_open"]))).sum() != 1:
        raise RuntimeError("TEST_CALENDAR_LAST_OPEN_MISSING")
    return prices


def flat_mean_prediction(day: pd.DataFrame) -> float:
    """Control A removes cross-sectional HGB dispersion; retains its daily mean."""
    return float(day.pred_hgb.mean())


def equal_shadow_target(shadow: dict[str, float]) -> dict[str, float]:
    """Control B preserves HGB_FACTOR_5 shadow support and target gross."""
    positive = sorted(t for t, w in shadow.items() if w > 0)
    if not positive:
        return {}
    each = float(sum(shadow.values()) / len(positive))
    return {t: each for t in positive}


def _write_frame(frame: pd.DataFrame, path: Path) -> str:
    frame.to_parquet(path, index=False)
    return sha(path)


def _rl_decider(models, days):
    import torch
    from rl_core import MAX_EXPOSURE, MAX_NAMES, policy_target

    def decide(signal, shares, values, nav):
        targets, logs = [], []
        with torch.no_grad():
            for seed, model in models:
                rows = []
                target = policy_target(model, days[signal], shares, values, nav,
                                       training=False, records=rows)
                targets.append(target)
                logs.append((seed, {r["ticker"]: r for r in rows}))
        names = set().union(*(set(x) for x in targets))
        combined = {t: float(sum(x.get(t, 0.) for x in targets) / len(targets)) for t in names}
        if len(combined) > MAX_NAMES:
            keep = set(sorted(combined, key=lambda t: (-combined[t], t))[:MAX_NAMES])
            combined = {t: w for t, w in combined.items() if t in keep}
        if sum(combined.values()) > MAX_EXPOSURE + 1e-6:
            raise RuntimeError("RL_TARGET_EXPOSURE")
        metadata = {}
        for t in set(shares) | names | set().union(*(set(x) for _, x in logs)):
            item = {}
            for seed, records in logs:
                row = records.get(t)
                if row is not None:
                    item[f"raw_action_logit_{seed}"] = row["raw_action_logit"]
                    item[f"projected_seed_weight_{seed}"] = row["target_weight"]
            if len(models) == 1:
                item["raw_action_logit"] = item.get(f"raw_action_logit_{models[0][0]}", np.nan)
            metadata[t] = item
        return combined, metadata
    return decide


def _opt_decider(day_map, bundle, spec, *, flatten=False, shadow=None, shadow_sink=None):
    from optimize_route import solve

    def decide(signal, shares, values, nav):
        day = day_map[signal]
        if shadow is not None:
            source = shadow.get(signal)
            if source is None:
                raise RuntimeError(f"SHADOW_TARGET_MISSING:{signal}")
            target = equal_shadow_target(source)
            diag = {"raw_targets": target.copy(), "solver_failed": False, "message": "SHADOW_EQUAL_WEIGHT"}
        elif spec is None:
            target = {str(t): .05 for t in day.loc[day.raw_rank.le(20), "ticker"]}
            diag = {"raw_targets": target.copy(), "solver_failed": False, "message": "RAW_FIXED"}
        else:
            if flatten:
                day = day.copy()
                day["pred_hgb_flat"] = flat_mean_prediction(day)
            target, diag = solve(day, shares, values, nav, bundle, spec, signal)
        if shadow_sink is not None:
            shadow_sink[signal] = target.copy()
        raw = diag["raw_targets"]
        metadata = {t: {"raw_target_weight": float(raw.get(t, 0.0)),
                        "solver_failed": bool(diag["solver_failed"]),
                        "solver_message": str(diag["message"])}
                    for t in set(shares) | set(target) | set(raw)}
        return target, metadata
    return decide


def _runtime(m, decision_inspect: Path, execution_inspect: Path,
             phase: str, candidate: str | None) -> dict:
    from runtime_gate import verify_runtime_gate
    runtime = m.get("runtime", {})
    decision_command = ["/usr/local/bin/python", "-B", "/worker/decision_service.py",
                        "--mode", "predict" if phase == "predict" else "target",
                        "--identity-sha", m["decision_bundle_identity_sha256"]]
    if phase == "account":
        decision_command.extend(["--candidate", str(candidate)])
    execution_command = ["/usr/local/bin/python", "-B", "/worker/test_worker.py",
                         *sys.argv[1:]]
    return verify_runtime_gate(
        decision_inspect, execution_inspect, r1_root=m["r1_host_root"],
        expected_image_id=IMAGE_ID, approved_test_source=m["test_source"]["mount_source"],
        approved_out_source=m["approved_out_source"],
        approved_ipc_source=runtime.get("approved_ipc_source"),
        approved_ipc_name=runtime.get("approved_ipc_name"),
        expected_decision_cmd=decision_command,
        expected_execution_cmd=execution_command)


def validate_private_channels(socket_path: Path, decision_inspect: Path,
                              execution_inspect: Path) -> None:
    if socket_path.resolve() != Path("/ipc/decision.sock").resolve():
        raise RuntimeError("DECISION_SOCKET_OUTSIDE_PRIVATE_IPC")
    roots = (Path("/out").resolve(), Path("/ipc").resolve())
    for path in (decision_inspect, execution_inspect):
        if not any(path.resolve().is_relative_to(root) for root in roots):
            raise RuntimeError("INSPECT_RECORD_OUTSIDE_PRIVATE_MOUNTS")


class DecisionClient:
    """One connection to an externally inspected, price-free decision runtime."""

    def __init__(self, path: Path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile("rwb", buffering=0)

    def ask(self, payload: dict) -> dict:
        message = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(message) > 2_000_000:
            raise RuntimeError("DECISION_REQUEST_TOO_LARGE")
        self.stream.write(message + b"\n")
        line = self.stream.readline(2_000_001)
        if not line or len(line) > 2_000_000:
            raise RuntimeError("DECISION_SERVICE_NO_RESPONSE")
        reply = json.loads(line)
        if not isinstance(reply, dict) or "error" in reply:
            raise RuntimeError(f"DECISION_SERVICE_ERROR:{reply.get('error', reply)}")
        return reply

    def close(self):
        try:
            try:
                self.ask({"op": "close"})
            except (OSError, RuntimeError):
                pass
        finally:
            self.stream.close()
            self.socket.close()


def _wire_rows(frame: pd.DataFrame) -> list[dict]:
    copy = frame.copy()
    if "signal_date" in copy:
        copy["signal_date"] = pd.to_datetime(copy.signal_date).dt.strftime("%Y-%m-%d")
    return json.loads(copy.to_json(orient="records"))


def _bound_hash(m: dict, suffix: str) -> str:
    matches = [item["sha256"] for item in m["bound_files"] if item["path"].endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"MODEL_IDENTITY_BINDING:{suffix}")
    return matches[0]


def _model_identity(m: dict, candidate: str) -> str:
    if candidate == "Raw":
        return "RAW_FIXED_5_PERCENT"
    if not candidate.startswith("RL_"):
        return _bound_hash(m, "models/hgb_2026092501.joblib")
    kind = "zero" if candidate == "RL_C_ZERO_UPDATE" else "selected"
    seeds = SEEDS if candidate in ("RL_C_ZERO_UPDATE", "RL_C_SELECTED_TARGET_MEAN") else (int(candidate.rsplit("_", 1)[-1]),)
    return "+".join(_bound_hash(m, f"rl_artifacts/C_{kind}_{seed}.pt") for seed in seeds)


def _read_prediction_receipt(out: Path, manifest_sha: str) -> dict:
    receipt = json.loads((out / "PREDICTION_SEAL.json").read_text(encoding="utf-8"))
    if receipt.get("status") != "NINE_SUPERVISED_PREDICTIONS_SEALED" or receipt.get("frozen_manifest_sha256") != manifest_sha:
        raise RuntimeError("PREDICTION_SEAL_MISMATCH")
    if sha(out / "all_supervised_predictions.parquet") != receipt["prediction_sha256"]:
        raise RuntimeError("PREDICTION_FILE_CHANGED")
    return receipt


def predict(m: dict, manifest_sha: str, out: Path, socket_path: Path, runtime: dict) -> None:
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("PREDICTION_OUTPUT_NOT_EMPTY")
    panel_file, _ = inspect_test_source(m, panel_only=True)
    sys.path.insert(0, str(TRAINED))
    from prepare import FEATURES
    panel = read_panel_projection(m, panel_file, FEATURES)
    rows = []
    client = DecisionClient(socket_path)
    try:
        for signal, day in panel.groupby("signal_date", sort=True):
            reply = client.ask({"op": "predict", "rows": _wire_rows(day)})
            scored = pd.DataFrame(reply["rows"])
            expected = set(zip(day.ticker.astype(str), day.security_id.astype(str), day.raw_rank.astype(int)))
            actual = set(zip(scored.ticker.astype(str), scored.security_id.astype(str), scored.raw_rank.astype(int)))
            if len(scored) != 40 or actual != expected:
                raise RuntimeError(f"PREDICTION_ROW_IDENTITY:{signal}")
            scored["signal_date"] = signal
            rows.append(scored)
    finally:
        client.close()
    prediction = pd.concat(rows, ignore_index=True)
    required = [f"pred_{name}" + (f"_{seed}" if name == "mlp" else "") for name, seed in MODEL_KEYS]
    required += ["pred_mlp_mean", "quantile_crossing"]
    if not set(required).issubset(prediction.columns) or not np.isfinite(prediction[required[:-1]].to_numpy(float)).all():
        raise RuntimeError("NINE_PREDICTION_COLUMNS_INVALID")
    out.mkdir(parents=True, exist_ok=True)
    pred_hash = _write_frame(prediction[["signal_date", "ticker", "security_id", "raw_rank", *required]],
                             out / "all_supervised_predictions.parquet")
    receipt = {"status": "NINE_SUPERVISED_PREDICTIONS_SEALED", "batch": BATCH,
               "frozen_manifest_sha256": manifest_sha,
               "test_source_identity_sha256": m["test_source"]["source_manifest_sha256"],
               "panel_sha256": m["test_source"]["panel"]["sha256"],
               "prediction_sha256": pred_hash, "rows": len(prediction),
               "max_signal_date": str(panel.signal_date.max().date()), "runtime": runtime}
    (out / "PREDICTION_SEAL.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("NINE_SUPERVISED_PREDICTIONS_SEALED_NO_NAV", flush=True)


def account(m: dict, manifest_sha: str, out: Path, candidate: str,
            socket_path: Path, runtime: dict) -> None:
    if candidate not in ROSTER:
        raise RuntimeError("CANDIDATE_NOT_FROZEN")
    _read_prediction_receipt(out, manifest_sha)
    index = ROSTER.index(candidate)
    previous = [f"ACCOUNT_{name}.json" for name in ROSTER[:index]]
    if any(not (out / name).is_file() for name in previous) or any((out / f"ACCOUNT_{name}.json").exists() for name in ROSTER[index:]):
        raise RuntimeError("ACCOUNT_ORDER_OR_REPLAY_VIOLATION")
    panel_file, price_file = inspect_test_source(m)
    sys.path.insert(0, str(TRAINED))
    from prepare import FEATURES
    from optimize_route import dates_for
    from logged_execution import run_logged_replay
    panel = read_panel_projection(m, panel_file, FEATURES)
    prices = read_prices_projection(m, price_file, panel)
    preds = pd.read_parquet(out / "all_supervised_predictions.parquet")
    panel = panel.merge(preds, on=["signal_date", "ticker", "security_id", "raw_rank"],
                        how="left", validate="one_to_one")
    if panel.pred_hgb.isna().any() or len(panel) != len(preds):
        raise RuntimeError("PREDICTION_PANEL_JOIN_FAILURE")
    stop = str(pd.Timestamp(m["test_source"]["last_completed_signal_session"]) + pd.Timedelta(days=2))
    signals, executions, signal_by_execution = dates_for(prices, panel, "2026-01-01", stop)
    if not signals or max(signals) > pd.Timestamp(m["test_source"]["last_completed_signal_session"]) or max(executions) > pd.Timestamp(m["test_source"]["last_available_execution_open"]):
        raise RuntimeError("INVALID_TEST_EXECUTION_CLOCK")
    day_map = {d: g for d, g in panel.groupby("signal_date", sort=True)}
    shadow = {}
    if candidate == "HGB_CONTROL_B_SHADOW_SET_GROSS_EQUAL_WEIGHT":
        prior = json.loads((out / "ACCOUNT_HGB_FACTOR_5.json").read_text(encoding="utf-8"))
        item = next(x for x in prior["files"] if x["path"] == "HGB_FACTOR_5_decisions.parquet")
        if sha(out / item["path"]) != item["sha256"]:
            raise RuntimeError("SHADOW_DECISIONS_CHANGED")
        decisions = pd.read_parquet(out / item["path"])
        for day, group in decisions.groupby("signal_date"):
            shadow[pd.Timestamp(day)] = {str(r.ticker): float(r.feasible_target_weight)
                                         for r in group.itertuples() if r.feasible_target_weight > 0}
    client = DecisionClient(socket_path)
    def decide(signal, shares, values, nav):
        reply = client.ask({"op": "target", "candidate": candidate,
                            "signal_date": str(signal.date()),
                            "rows": _wire_rows(day_map[signal]),
                            "shares": shares, "values": values, "nav": float(nav),
                            "shadow": shadow.get(signal, {}) if shadow else {}})
        target, metadata = reply["target"], reply["metadata"]
        if not isinstance(target, dict) or not isinstance(metadata, dict):
            raise RuntimeError("DECISION_TARGET_SCHEMA")
        w = np.asarray(list(target.values()), dtype=float)
        max_gross = .95 if candidate.startswith("RL_") else 1.0
        fallback = any(bool(row.get("solver_failed")) for row in metadata.values())
        if (not np.isfinite(w).all() or (w < 0).any() or
            ((w > .10 + 1e-6).any() and not (fallback or candidate == "HGB_CONTROL_B_SHADOW_SET_GROSS_EQUAL_WEIGHT")) or
            w.sum() > max_gross + 1e-6):
            raise RuntimeError("DECISION_TARGET_INFEASIBLE")
        return target, metadata
    try:
        result, decisions, records = run_logged_replay(
            candidate, decide, prices, executions, signal_by_execution,
            input_identity=m["test_source"]["source_manifest_sha256"],
            model_identity=_model_identity(m, candidate))
    finally:
        client.close()
    files = []
    for suffix, frame in (("daily", result.daily), ("trades", result.trades),
                          ("contributions", result.contributions),
                          ("decisions", decisions), ("actions_fills", records)):
        rel = f"{candidate}_{suffix}.parquet"
        files.append({"path": rel, "sha256": _write_frame(frame, out / rel)})
    receipt = {"status": "SINGLE_ACCOUNT_SUBMITTED_NO_REPORT", "batch": BATCH,
               "candidate": candidate, "frozen_manifest_sha256": manifest_sha,
               "prediction_seal_sha256": sha(out / "PREDICTION_SEAL.json"),
               "test_source_identity_sha256": m["test_source"]["source_manifest_sha256"],
               "panel_sha256": m["test_source"]["panel"]["sha256"],
               "prices_sha256": m["test_source"]["prices"]["sha256"],
               "signal_count": len(signals),
               "first_signal_date": str(min(signals).date()),
               "last_signal_date": str(max(signals).date()),
               "first_execution_date": str(min(executions).date()),
               "last_execution_date": str(max(executions).date()),
               "initial_cash_nav": 1.0,
               "runtime": runtime, "files": files}
    (out / f"ACCOUNT_{candidate}.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"ACCOUNT_SUBMITTED_NO_REPORT:{candidate}", flush=True)


def seal(m: dict, manifest_sha: str, out: Path) -> None:
    prediction = _read_prediction_receipt(out, manifest_sha)
    files = [{"path": "all_supervised_predictions.parquet", "sha256": prediction["prediction_sha256"]},
             {"path": "PREDICTION_SEAL.json", "sha256": sha(out / "PREDICTION_SEAL.json")}]
    ids = [prediction["runtime"]["decision_container_id"]]
    reference_dates = None
    for candidate in ROSTER:
        receipt_path = out / f"ACCOUNT_{candidate}.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (receipt.get("status") != "SINGLE_ACCOUNT_SUBMITTED_NO_REPORT" or
            receipt.get("candidate") != candidate or
            receipt.get("frozen_manifest_sha256") != manifest_sha or
            receipt.get("prediction_seal_sha256") != files[1]["sha256"] or
            receipt.get("test_source_identity_sha256") != m["test_source"]["source_manifest_sha256"] or
            receipt.get("panel_sha256") != m["test_source"]["panel"]["sha256"] or
            receipt.get("prices_sha256") != m["test_source"]["prices"]["sha256"] or
            receipt.get("initial_cash_nav") != 1.0):
            raise RuntimeError(f"ACCOUNT_RECEIPT_MISMATCH:{candidate}")
        daily_item = next((x for x in receipt["files"] if x["path"] == f"{candidate}_daily.parquet"), None)
        if daily_item is None or sha(out / daily_item["path"]) != daily_item["sha256"]:
            raise RuntimeError(f"ACCOUNT_DAILY_CHANGED:{candidate}")
        dates = pd.read_parquet(out / daily_item["path"],
                                columns=["signal_date", "execution_date", "pretrade_nav"])
        if dates.empty or len(dates) != receipt.get("signal_count") or not np.isclose(float(dates.pretrade_nav.iloc[0]), 1.0, atol=1e-12):
            raise RuntimeError(f"ACCOUNT_INITIAL_STATE_OR_COVERAGE:{candidate}")
        if (str(pd.Timestamp(dates.signal_date.iloc[0]).date()) != receipt.get("first_signal_date") or
            str(pd.Timestamp(dates.signal_date.iloc[-1]).date()) != receipt.get("last_signal_date") or
            str(pd.Timestamp(dates.execution_date.iloc[0]).date()) != receipt.get("first_execution_date") or
            str(pd.Timestamp(dates.execution_date.iloc[-1]).date()) != receipt.get("last_execution_date")):
            raise RuntimeError(f"ACCOUNT_RECEIPT_DATE_MISMATCH:{candidate}")
        sequence = list(zip(pd.to_datetime(dates.signal_date).astype(str),
                            pd.to_datetime(dates.execution_date).astype(str)))
        if reference_dates is None:
            reference_dates = sequence
        elif sequence != reference_dates:
            raise RuntimeError(f"ACCOUNT_DATE_COVERAGE_DIFFERS:{candidate}")
        ids.append(receipt["runtime"]["decision_container_id"])
        files.append({"path": receipt_path.name, "sha256": sha(receipt_path)})
        files.extend(receipt["files"])
    if len(set(ids)) != 1 + len(ROSTER):
        raise RuntimeError("DECISION_RUNTIME_NOT_FRESH_PER_PHASE")
    expected = {"all_supervised_predictions.parquet", "PREDICTION_SEAL.json"}
    expected.update(f"ACCOUNT_{c}.json" for c in ROSTER)
    expected.update(f"{c}_{k}.parquet" for c in ROSTER for k in
                    ("daily", "trades", "contributions", "decisions", "actions_fills"))
    if {x["path"] for x in files} != expected or len(files) != len(expected):
        raise RuntimeError("INCOMPLETE_ALL_ACCOUNT_SUBMISSION")
    for item in files:
        if sha(_under(out, str(out / item["path"]))) != item["sha256"]:
            raise RuntimeError(f"SUBMISSION_CHANGED:{item['path']}")
    if (out / "SUBMISSION_SEAL.json").exists():
        raise RuntimeError("SUBMISSION_ALREADY_SEALED")
    receipt = {"status": "ALL_NINE_SUBMISSIONS_SEALED_NO_REPORT", "batch": BATCH,
               "frozen_manifest_sha256": manifest_sha, "test_source_identity_sha256": m["test_source"]["source_manifest_sha256"],
               "asof_utc": ASOF, "roster": ROSTER, "files": files,
               "performance_reported": False}
    (out / "SUBMISSION_SEAL.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("ALL_NINE_SUBMISSIONS_SEALED_NO_REPORT", flush=True)


def report(m: dict, manifest_sha: str, out: Path, expected_submission_sha: str) -> None:
    seal_path = out / "SUBMISSION_SEAL.json"
    if sha(seal_path) != _hex(expected_submission_sha, "submission seal"):
        raise RuntimeError("SUBMISSION_SEAL_EXTERNAL_HASH_MISMATCH")
    receipt = json.loads(seal_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "ALL_NINE_SUBMISSIONS_SEALED_NO_REPORT" or receipt.get("frozen_manifest_sha256") != manifest_sha or tuple(receipt.get("roster", ())) != ROSTER:
        raise RuntimeError("INCOMPLETE_SUBMISSION_SEAL")
    expected_paths = {"all_supervised_predictions.parquet", "PREDICTION_SEAL.json"}
    expected_paths.update(f"ACCOUNT_{name}.json" for name in ROSTER)
    expected_paths.update(f"{name}_{kind}.parquet" for name in ROSTER
                          for kind in ("daily", "trades", "contributions", "decisions", "actions_fills"))
    if {item["path"] for item in receipt.get("files", ())} != expected_paths or len(receipt.get("files", ())) != len(expected_paths):
        raise RuntimeError("INCOMPLETE_SUBMISSION_FILES")
    for item in receipt["files"]:
        p = _under(out, str(out / item["path"]))
        if sha(p) != item["sha256"]:
            raise RuntimeError(f"SUBMISSION_CHANGED:{item['path']}")
    if (out / "TEST_REPORT.json").exists():
        raise RuntimeError("TEST_REPORT_ALREADY_EXISTS")
    rows = []
    for candidate in ROSTER:
        daily = pd.read_parquet(out / f"{candidate}_daily.parquet")
        trades = pd.read_parquet(out / f"{candidate}_trades.parquet")
        decisions = pd.read_parquet(out / f"{candidate}_decisions.parquet")
        details = pd.read_parquet(out / f"{candidate}_actions_fills.parquet")
        nav = daily.nav.to_numpy(float)
        drawdown = nav / np.maximum.accumulate(np.r_[1., nav])[1:] - 1
        sold = details.loc[details.side.eq("SELL")]
        bought = details.loc[details.side.eq("BUY")]
        partial_sells = int(sold.sell_shares_over_before_shares.lt(1 - 1e-8).sum())
        full_exits = int(sold.shares_after_execution.le(1e-14).sum())
        added = int(bought.shares_before_execution.gt(1e-14).sum())
        traded_days = int(trades.execution_date.nunique()) if not trades.empty else 0
        fallback = (int(decisions.loc[decisions.solver_failed, "signal_date"].nunique())
                    if "solver_failed" in decisions else 0)
        top_weights = []
        nav_by_date = daily.set_index("execution_date").nav
        for date, group in details.loc[details.shares_after_execution.gt(1e-14)].groupby("execution_date"):
            if np.isfinite(group.execution_open.to_numpy(float)).all():
                top_weights.append(float((group.shares_after_execution * group.execution_open).max()
                                         / nav_by_date.loc[date]))
        reasons = details.unfilled_or_unresolved_reason.value_counts(dropna=True).to_dict()
        rows.append({"candidate": candidate, "days": len(daily),
                     "last_nav": float(nav[-1]), "max_drawdown": float(drawdown.min()),
                     "fees": float(daily.transaction_cost_amount.sum()),
                     "turnover": float(daily.turnover.sum()),
                     "mean_cash_weight": float(daily.cash_weight.mean()),
                     "minimum_cash_weight": float(daily.cash_weight.min()),
                     "mean_gross_exposure": float(daily.gross_exposure.mean()),
                     "maximum_gross_exposure": float(daily.gross_exposure.max()),
                     "mean_actual_name_count": float(daily.actual_name_count.mean()),
                     "maximum_target_weight_sum": float(decisions.groupby("signal_date").feasible_target_weight.sum().max()),
                     "maximum_observable_single_name_weight": max(top_weights) if top_weights else None,
                     "single_name_weight_observed_days": len(top_weights),
                     "partial_sells": partial_sells, "full_exits": full_exits,
                     "add_to_existing": added, "trades": len(trades),
                     "no_trade_days": len(daily) - traded_days,
                     "solver_fallback_dates": fallback,
                     "nonfill_or_partial_reasons": {str(k): int(v) for k, v in reasons.items()},
                     "blocked_sells": int(daily.blocked_sell_count.sum()),
                     "skipped_buys": int(daily.skipped_buy_count.sum()),
                     "max_nav_identity_error": float(daily.nav_identity_error.abs().max())})
    raw = next(r for r in rows if r["candidate"] == "Raw")["last_nav"]
    summary = {"status": "FROZEN_2026_PRICE_COORDINATE_PROXY_EVALUATED",
               "batch": BATCH, "asof_utc": ASOF, "frozen_manifest_sha256": manifest_sha,
               "submission_seal_sha256": sha(seal_path), "raw_fallback_retained": True,
               "prior_2026_research_exposure": True, "shareholder_total_return_certified": False,
               "accounts": [{**r, "last_nav_minus_raw": r["last_nav"] - raw} for r in rows]}
    (out / "TEST_REPORT.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("FROZEN_2026_REPORT_WRITTEN", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("predict", "account", "seal", "report"))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--candidate", choices=ROSTER)
    parser.add_argument("--decision-socket", type=Path)
    parser.add_argument("--decision-inspect", type=Path)
    parser.add_argument("--execution-inspect", type=Path)
    parser.add_argument("--submission-seal-sha256")
    args = parser.parse_args()
    m, manifest_sha = verify_frozen_manifest(args.manifest, args.manifest_sha256)
    if args.phase in ("predict", "account"):
        if not all((args.decision_socket, args.decision_inspect, args.execution_inspect)):
            raise RuntimeError("DECISION_RUNTIME_AND_INSPECT_REQUIRED")
        validate_private_channels(args.decision_socket, args.decision_inspect,
                                  args.execution_inspect)
        if not args.out.resolve().is_relative_to(Path("/out").resolve()):
            raise RuntimeError("OUTPUT_OUTSIDE_PRIVATE_MOUNT")
        runtime = _runtime(m, args.decision_inspect, args.execution_inspect,
                           args.phase, args.candidate)
        if args.phase == "predict":
            predict(m, manifest_sha, args.out, args.decision_socket, runtime)
        else:
            if args.candidate is None:
                raise RuntimeError("FROZEN_ACCOUNT_CANDIDATE_REQUIRED")
            account(m, manifest_sha, args.out, args.candidate, args.decision_socket, runtime)
    elif args.phase == "seal":
        seal(m, manifest_sha, args.out)
    else:
        if args.submission_seal_sha256 is None:
            raise RuntimeError("EXTERNAL_SUBMISSION_SEAL_HASH_REQUIRED")
        report(m, manifest_sha, args.out, args.submission_seal_sha256)


if __name__ == "__main__":
    main()
