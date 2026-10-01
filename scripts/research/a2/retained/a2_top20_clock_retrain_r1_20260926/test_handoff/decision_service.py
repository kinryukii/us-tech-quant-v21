"""One-day R1 inference/target service for the price-blind decision container.

The execution container sends only the current signal's 40 feature rows and
one account's pretrade state. This process never receives execution prices or
test files, and is restarted for each frozen account. The existing R1 model,
optimizer and RL policy functions define every prediction and target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import socket
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np
import pandas as pd


MAX_REQUEST_BYTES = 2_000_000
MIN_SIGNAL = pd.Timestamp("2026-01-01")
# The fixed R1 as-of is 2026-09-25 15:34:48 UTC, before the ET close.
MAX_SIGNAL = pd.Timestamp("2026-09-24")
IDENTITY = ("signal_date", "ticker", "security_id", "raw_rank")
TRAINING_SEAL_SHA = "1607b78294b88fea5bb565b9b22c99fccf3bb1817d1cacce2b9126336263ee3d"


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_projection(root: Path, expected_identity_sha: str | None = None) -> str:
    """Verify the curated, price-free copy before any model is loaded."""
    identity_path = root / "IDENTITY.json"
    identity_sha = _sha(identity_path)
    if expected_identity_sha is not None and identity_sha != expected_identity_sha:
        raise RuntimeError("DECISION_PROJECTION_IDENTITY_CHANGED")
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if (identity.get("status") != "R1_DECISION_PROJECTION_PRETEST" or
            identity.get("source_training_seal_sha256") != TRAINING_SEAL_SHA):
        raise RuntimeError("DECISION_PROJECTION_WRONG_BATCH")
    entries = identity.get("files")
    if not isinstance(entries, list) or len(entries) != 21:
        raise RuntimeError("DECISION_PROJECTION_FILE_COUNT")
    listed = set()
    for item in entries:
        rel = item.get("path")
        if not isinstance(rel, str) or rel in listed or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise RuntimeError("DECISION_PROJECTION_INVALID_PATH")
        path = root / rel
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != item.get("bytes")
                or _sha(path) != item.get("sha256")):
            raise RuntimeError(f"DECISION_PROJECTION_FILE_CHANGED:{rel}")
        listed.add(rel)
    forbidden = ("data", "prices.parquet", "pre2026_oof.parquet", "opt_artifacts",
                 "rl_training", "test", "test_source", "performance")
    if any((root / x).exists() for x in forbidden):
        raise RuntimeError("DECISION_PROJECTION_CONTAINS_MARKET_OR_OUTPUT")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("DECISION_PROJECTION_SYMLINK")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != listed | {"IDENTITY.json"}:
        raise RuntimeError("DECISION_PROJECTION_EXTRA_OR_MISSING_FILE")
    return identity_sha


def _safe(value):
    """Strict JSON: missing numerical diagnostics become null, never NaN."""
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _nonnegative_map(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label}_MUST_BE_OBJECT")
    result = {}
    for key, x in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{label}_INVALID_TICKER")
        x = float(x)
        if not math.isfinite(x) or x < 0:
            raise ValueError(f"{label}_INVALID_VALUE")
        result[key] = x
    return result


class DecisionEngine:
    def __init__(self, mode: str, candidate: str | None,
                 code_root: Path, artifacts_root: Path):
        if mode not in ("predict", "target"):
            raise ValueError("INVALID_SERVICE_MODE")
        if not code_root.is_dir() or not artifacts_root.is_dir():
            raise RuntimeError("FROZEN_CODE_OR_ARTIFACT_ROOT_MISSING")
        sys.path.insert(0, str(code_root))
        # This import contributes the fixed roster and the same target
        # adapters used by the original incomplete in-process test worker.
        import test_worker as worker
        import prepare

        self.worker = worker
        self.features = tuple(prepare.FEATURES)
        self.prediction_columns = tuple(
            f"pred_{name}" + (f"_{seed}" if name == "mlp" else "")
            for name, seed in worker.MODEL_KEYS
        )
        self.mode = mode
        self.candidate = candidate
        self.last_date: pd.Timestamp | None = None
        if mode == "predict":
            if candidate is not None:
                raise ValueError("PREDICT_MODE_HAS_NO_CANDIDATE")
            import joblib
            self.models = [
                (name, seed, joblib.load(artifacts_root / "models" /
                                        f"{name}_{seed}.joblib"))
                for name, seed in worker.MODEL_KEYS
            ]
        else:
            if candidate not in worker.ROSTER:
                raise ValueError("CANDIDATE_OUTSIDE_FROZEN_ROSTER")
            self.risk = None
            self.rl_models = None
            if candidate in ("HGB_DIAG_5", "HGB_FACTOR_5",
                             "HGB_CONTROL_A_DAILY_MEAN"):
                from risk_aux import load_bundle
                self.risk = load_bundle(artifacts_root / "risk_artifacts" /
                                        "final_pre2026.joblib")
            if candidate.startswith("RL_"):
                from rl_core import FEATURES as RL_FEATURES
                import torch
                from rl_core import Policy

                norm_path = artifacts_root / "rl_artifacts" / "C_normalization.npz"
                with np.load(norm_path, allow_pickle=False) as norm:
                    self.rl_mean = norm["mean"].copy()
                    self.rl_scale = norm["scale"].copy()
                if (self.rl_mean.shape != (len(RL_FEATURES),) or
                    self.rl_scale.shape != self.rl_mean.shape or
                    not np.isfinite(self.rl_mean).all() or
                    not np.isfinite(self.rl_scale).all() or
                    (self.rl_scale <= 0).any()):
                    raise RuntimeError("RL_FROZEN_NORMALIZATION_INVALID")
                kind = "zero" if candidate == "RL_C_ZERO_UPDATE" else "selected"
                seeds = (worker.SEEDS if candidate in
                         ("RL_C_SELECTED_TARGET_MEAN", "RL_C_ZERO_UPDATE")
                         else (int(candidate.rsplit("_", 1)[-1]),))
                self.rl_models = []
                for seed in seeds:
                    model = Policy(len(RL_FEATURES) + 4)
                    state = torch.load(artifacts_root / "rl_artifacts" /
                                       f"C_{kind}_{seed}.pt", map_location="cpu",
                                       weights_only=True)
                    model.load_state_dict(state)
                    model.eval()
                    self.rl_models.append((seed, model))

    def _day(self, rows, *, predictions: bool):
        if not isinstance(rows, list) or len(rows) != 40 or not all(isinstance(r, dict) for r in rows):
            raise ValueError("CURRENT_DAY_MUST_HAVE_40_ROWS")
        allowed = set(IDENTITY) | set(self.features)
        if predictions:
            allowed |= set(self.prediction_columns) | {"pred_mlp_mean", "quantile_crossing"}
        if any(set(r) - allowed for r in rows):
            raise ValueError("NON_WHITELISTED_DECISION_FIELD")
        if any(not allowed.issuperset(r) or
               not (set(IDENTITY) | set(self.features)).issubset(r) for r in rows):
            raise ValueError("CURRENT_DAY_REQUIRED_FIELD_MISSING")
        if predictions and any(not set(self.prediction_columns).issubset(r) for r in rows):
            raise ValueError("CURRENT_DAY_PREDICTION_MISSING")
        day = pd.DataFrame(rows)
        date_values = pd.to_datetime(day.signal_date, errors="raise").unique()
        if len(date_values) != 1:
            raise ValueError("MIXED_SIGNAL_DATES")
        signal = pd.Timestamp(date_values[0])
        if (signal.tzinfo is not None or signal < MIN_SIGNAL or signal > MAX_SIGNAL or
            (self.last_date is not None and signal <= self.last_date)):
            raise ValueError("SIGNAL_DATE_OUTSIDE_FIXED_MONOTONE_WINDOW")
        if day.ticker.isna().any() or day.security_id.isna().any() or day.ticker.duplicated().any():
            raise ValueError("CURRENT_DAY_SECURITY_IDENTITY")
        if not all(isinstance(t, str) and t for t in day.ticker):
            raise ValueError("CURRENT_DAY_TICKER_TYPE")
        ranks = pd.to_numeric(day.raw_rank, errors="raise").to_numpy(float)
        if not np.array_equal(np.sort(ranks), np.arange(1, 41)):
            raise ValueError("CURRENT_DAY_TOP40_RANKS")
        day["signal_date"] = signal
        day["raw_rank"] = ranks.astype(int)
        numeric = day[list(self.features)].to_numpy(dtype=float)
        if np.isinf(numeric).any():
            raise ValueError("INFINITE_CURRENT_DAY_FEATURE")
        if predictions:
            pred = day[list(self.prediction_columns)].to_numpy(dtype=float)
            if not np.isfinite(pred).all():
                raise ValueError("NONFINITE_FROZEN_PREDICTION")
        return signal, day

    def handle(self, request: dict) -> dict:
        if not isinstance(request, dict):
            raise ValueError("REQUEST_MUST_BE_OBJECT")
        op = request.get("op")
        if op == "close":
            return {"closed": True}
        if op != self.mode:
            raise ValueError("OPERATION_DOES_NOT_MATCH_SERVICE_MODE")
        signal, day = self._day(request.get("rows"), predictions=op == "target")
        if op == "predict":
            for name, seed, model in self.models:
                values = (model.predict_proba(day[list(self.features)])[:, 1]
                          if name == "logistic" else model.predict(day[list(self.features)]))
                col = f"pred_{name}" + (f"_{seed}" if name == "mlp" else "")
                day[col] = np.asarray(values, dtype=float)
            day["pred_mlp_mean"] = .5 * (day.pred_mlp_2026092501 + day.pred_mlp_2026092502)
            day["quantile_crossing"] = day.pred_q10.gt(day.pred_q50) | day.pred_q50.gt(day.pred_q90)
            if not np.isfinite(day[list(self.prediction_columns)].to_numpy(float)).all():
                raise RuntimeError("NONFINITE_FROZEN_MODEL_OUTPUT")
            cols = [*IDENTITY, *self.prediction_columns, "pred_mlp_mean", "quantile_crossing"]
            result = {"rows": _safe(day[cols].assign(signal_date=str(signal.date()))
                                     .to_dict(orient="records"))}
        else:
            if request.get("candidate") != self.candidate:
                raise ValueError("CANDIDATE_DOES_NOT_MATCH_FIXED_PROCESS")
            if pd.Timestamp(request.get("signal_date")) != signal:
                raise ValueError("ACCOUNT_SIGNAL_DATE_MISMATCH")
            shares = _nonnegative_map(request.get("shares"), "SHARES")
            values = _nonnegative_map(request.get("values"), "VALUES")
            nav = float(request.get("nav"))
            if not math.isfinite(nav) or nav <= 0 or not set(values).issubset(shares):
                raise ValueError("INVALID_PRETRADE_ACCOUNT_STATE")
            if sum(values.values()) > nav * (1 + 1e-6):
                raise ValueError("UNFUNDED_PRETRADE_ACCOUNT_STATE")
            day_map = {signal: day}
            if self.candidate == "Raw":
                decider = self.worker._opt_decider(day_map, None, None)
            elif self.candidate in ("HGB_DIAG_5", "HGB_FACTOR_5"):
                from optimize_route import SPECS
                decider = self.worker._opt_decider(day_map, self.risk, SPECS[self.candidate])
            elif self.candidate == "HGB_CONTROL_A_DAILY_MEAN":
                decider = self.worker._opt_decider(day_map, self.risk,
                    ("pred_hgb_flat", "factor_shrink", 5.0, 0.0), flatten=True)
            elif self.candidate == "HGB_CONTROL_B_SHADOW_SET_GROSS_EQUAL_WEIGHT":
                shadow = _nonnegative_map(request.get("shadow"), "SHADOW")
                decider = self.worker._opt_decider(day_map, None, None,
                                                   shadow={signal: shadow})
            else:
                from rl_core import build_days
                days = build_days(day, self.rl_mean, self.rl_scale)
                decider = self.worker._rl_decider(self.rl_models, days)
            target, metadata = decider(signal, shares, values, nav)
            if any(not math.isfinite(float(w)) or float(w) < 0 for w in target.values()):
                raise RuntimeError("FROZEN_POLICY_INVALID_TARGET")
            result = {"target": _safe(target), "metadata": _safe(metadata)}
        self.last_date = signal
        return result


def serve(engine: DecisionEngine, socket_path: Path):
    if socket_path != Path("/ipc/decision.sock") or not socket_path.parent.is_dir():
        raise RuntimeError("PRIVATE_IPC_SOCKET_REQUIRED")
    if socket_path.exists():
        raise RuntimeError("STALE_IPC_SOCKET_MUST_BE_RESOLVED_BY_ORCHESTRATOR")
    bound = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            bound = True
            os.chmod(socket_path, 0o600)
            server.listen(1)
            with server.accept()[0] as connection:
                with connection.makefile("rwb", buffering=0) as stream:
                    while True:
                        line = stream.readline(MAX_REQUEST_BYTES + 1)
                        if not line:
                            break
                        if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
                            raise RuntimeError("IPC_REQUEST_TOO_LARGE_OR_UNTERMINATED")
                        try:
                            request = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON_NUMBER")))
                            reply = engine.handle(request)
                        except Exception as exc:
                            stream.write((json.dumps({"error": f"{type(exc).__name__}:{exc}"}) + "\n").encode())
                            raise
                        stream.write((json.dumps(_safe(reply), allow_nan=False, separators=(",", ":")) + "\n").encode())
                        if reply.get("closed"):
                            break
    finally:
        if bound:
            socket_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("predict", "target"))
    parser.add_argument("--candidate")
    parser.add_argument("--code-root", type=Path, default=Path("/bundle"))
    parser.add_argument("--artifacts-root", type=Path, default=Path("/bundle"))
    parser.add_argument("--identity-sha")
    parser.add_argument("--socket", type=Path, default=Path("/ipc/decision.sock"))
    args = parser.parse_args()
    if os.environ.get("R1_VERIFIED_ISOLATION") != "1":
        raise RuntimeError("VERIFIED_CONTAINER_CONFIGURATION_REQUIRED")
    if Path("/test").exists() or (args.code_root / "data" / "prices.parquet").exists() or \
            (args.artifacts_root / "data" / "prices.parquet").exists():
        raise RuntimeError("DECISION_CONTAINER_HAS_PRICE_OR_TEST_MOUNT")
    if args.code_root.resolve() != args.artifacts_root.resolve():
        raise RuntimeError("CURATED_DECISION_BUNDLE_REQUIRED")
    verify_projection(args.code_root, args.identity_sha)
    sys.dont_write_bytecode = True
    engine = DecisionEngine(args.mode, args.candidate, args.code_root, args.artifacts_root)
    serve(engine, args.socket)


if __name__ == "__main__":
    main()
