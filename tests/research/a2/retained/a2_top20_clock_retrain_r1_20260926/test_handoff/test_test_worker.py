"""No-market technical checks for the frozen R1 test worker."""
from __future__ import annotations

import json
import contextlib
import io
import multiprocessing
import socket
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

import test_worker as worker


def _synthetic_server(path: str, mode: str, candidate: str | None) -> None:
    import decision_service
    bundle = worker.WORKER_DIR / "decision_bundle"
    engine = decision_service.DecisionEngine(mode, candidate, bundle, bundle)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen(1)
        with server.accept()[0] as connection:
            with connection.makefile("rwb", buffering=0) as stream:
                while True:
                    request = json.loads(stream.readline())
                    reply = engine.handle(request)
                    stream.write((json.dumps(reply, allow_nan=False) + "\n").encode())
                    if request["op"] == "close":
                        return


def _one_ipc_process(mode: str, candidate: str | None, request: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r1.sock"
        process = multiprocessing.get_context("spawn").Process(
            target=_synthetic_server, args=(str(path), mode, candidate))
        process.start()
        for _ in range(200):
            if path.exists():
                break
            if process.exitcode is not None:
                raise RuntimeError(f"synthetic decision process exited {process.exitcode}")
            time.sleep(.05)
        else:
            raise RuntimeError("synthetic decision socket unavailable")
        client = worker.DecisionClient(path)
        try:
            reply = client.ask(request)
        finally:
            client.close()
        process.join(10)
        if process.exitcode != 0:
            raise RuntimeError(f"synthetic decision process exit {process.exitcode}")
        return reply


def _synthetic_seal_report() -> None:
    manifest_sha = "a" * 64
    source_sha, panel_sha, prices_sha = "b" * 64, "c" * 64, "d" * 64
    source = {"test_source": {"source_manifest_sha256": source_sha,
                              "panel": {"sha256": panel_sha},
                              "prices": {"sha256": prices_sha}}}
    date, execution = pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        pred_sha = worker._write_frame(pd.DataFrame({"signal_date": [date], "ticker": ["T00"]}),
                                       out / "all_supervised_predictions.parquet")
        prediction = {"status": "NINE_SUPERVISED_PREDICTIONS_SEALED",
                      "frozen_manifest_sha256": manifest_sha, "prediction_sha256": pred_sha,
                      "runtime": {"decision_container_id": "predict"}}
        (out / "PREDICTION_SEAL.json").write_text(json.dumps(prediction), encoding="utf-8")
        prediction_seal_sha = worker.sha(out / "PREDICTION_SEAL.json")
        daily = pd.DataFrame({"signal_date": [date], "execution_date": [execution],
            "pretrade_nav": [1.0], "nav": [1.0], "transaction_cost_amount": [0.0],
            "turnover": [0.0], "cash_weight": [1.0], "gross_exposure": [0.0],
            "actual_name_count": [0], "blocked_sell_count": [0],
            "skipped_buy_count": [0], "nav_identity_error": [0.0]})
        decisions = pd.DataFrame({"signal_date": [date], "ticker": ["T00"],
                                  "feasible_target_weight": [0.0], "solver_failed": [False]})
        details = pd.DataFrame({"execution_date": [execution], "side": ["NONE"],
            "sell_shares_over_before_shares": [np.nan], "shares_after_execution": [0.0],
            "shares_before_execution": [0.0], "execution_open": [np.nan],
            "unfilled_or_unresolved_reason": [None]})
        empty = pd.DataFrame({"execution_date": pd.Series(dtype="datetime64[ns]")})
        for i, candidate in enumerate(worker.ROSTER):
            files = []
            for kind, frame in (("daily", daily), ("trades", empty),
                                ("contributions", empty), ("decisions", decisions),
                                ("actions_fills", details)):
                path = f"{candidate}_{kind}.parquet"
                files.append({"path": path, "sha256": worker._write_frame(frame, out / path)})
            receipt = {"status": "SINGLE_ACCOUNT_SUBMITTED_NO_REPORT",
                "candidate": candidate, "frozen_manifest_sha256": manifest_sha,
                "prediction_seal_sha256": prediction_seal_sha,
                "test_source_identity_sha256": source_sha, "panel_sha256": panel_sha,
                "prices_sha256": prices_sha, "initial_cash_nav": 1.0,
                "signal_count": 1, "first_signal_date": str(date.date()),
                "last_signal_date": str(date.date()),
                "first_execution_date": str(execution.date()),
                "last_execution_date": str(execution.date()),
                "runtime": {"decision_container_id": f"account{i}"}, "files": files}
            (out / f"ACCOUNT_{candidate}.json").write_text(json.dumps(receipt), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            worker.seal(source, manifest_sha, out)
            worker.report(source, manifest_sha, out, worker.sha(out / "SUBMISSION_SEAL.json"))
        summary = json.loads((out / "TEST_REPORT.json").read_text(encoding="utf-8"))
        assert len(summary["accounts"]) == 9
        assert all(x["last_nav"] == 1.0 for x in summary["accounts"])


def main() -> None:
    day = pd.DataFrame({"pred_hgb": [-0.10, 0.02, 0.11]})
    flat = np.full(len(day), worker.flat_mean_prediction(day))
    assert np.isclose(flat.mean(), day.pred_hgb.mean())
    assert np.all(flat == flat[0])

    shadow = {"A": 0.07, "B": 0.03, "C": 0.0}
    equal = worker.equal_shadow_target(shadow)
    assert set(equal) == {"A", "B"}
    assert np.isclose(sum(equal.values()), sum(shadow.values()))
    assert equal["A"] == equal["B"]
    assert worker.equal_shadow_target({}) == {}
    sys.path.insert(0, str(worker.TRAINED))
    signal = pd.Timestamp("2025-01-02")
    decide = worker._opt_decider({signal: day}, None, None,
                                 shadow={signal: shadow})
    actual, metadata = decide(signal, {"A": 1.0}, {"A": 0.04}, 1.0)
    assert actual == equal and metadata["A"]["solver_message"] == "SHADOW_EQUAL_WEIGHT"
    wire = worker._wire_rows(pd.DataFrame({"signal_date": [signal], "x": [np.nan]}))
    assert wire == [{"signal_date": "2025-01-02", "x": None}]
    try:
        worker.validate_private_channels(Path("/tmp/foreign.sock"),
            Path("/out/decision.json"), Path("/out/execution.json"))
    except RuntimeError as exc:
        assert "SOCKET_OUTSIDE_PRIVATE_IPC" in str(exc)
    else:
        raise AssertionError("foreign decision socket accepted")
    try:
        worker.validate_private_channels(Path("/ipc/decision.sock"),
            Path("/tmp/foreign-inspect.json"), Path("/out/execution.json"))
    except RuntimeError as exc:
        assert "INSPECT_RECORD_OUTSIDE_PRIVATE_MOUNTS" in str(exc)
    else:
        raise AssertionError("foreign inspect record accepted")

    if hasattr(socket, "AF_UNIX"):
        features = ["raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d",
                    "ret_20d", "realized_vol_20d", "downside_vol_20d",
                    "max_drawdown_20d", "volume_ratio_5d_20d", "price_vs_ma20",
                    "distance_from_high_20d", *[f"lag_ret_{i:02d}" for i in range(10)]]
        current = [dict(signal_date="2026-01-02", ticker=f"T{i:02d}",
                        security_id=f"S{i:02d}", raw_rank=i + 1,
                        **{name: 0.0 for name in features}) for i in range(40)]
        scored = _one_ipc_process("predict", None, {"op": "predict", "rows": current})["rows"]
        assert len(scored) == 40 and all("pred_hgb" in row for row in scored)
        enriched = [{**a, **b} for a, b in zip(current, scored)]
        decided = _one_ipc_process("target", "Raw", {"op": "target", "candidate": "Raw",
            "signal_date": "2026-01-02", "rows": enriched,
            "shares": {}, "values": {}, "nav": 1.0, "shadow": {}})
        assert len(decided["target"]) == 20 and np.isclose(sum(decided["target"].values()), 1.0)
    else:
        print("IPC_UNIX_SOCKET_HOST_UNAVAILABLE")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "unfinished.json"
        path.write_text(json.dumps({"status": "PRETEST_BINDING_INCOMPLETE"}), encoding="utf-8")
        try:
            worker.verify_frozen_manifest(path, worker.sha(path))
        except RuntimeError as exc:
            assert "FULL_BATCH_FREEZE_REQUIRED" in str(exc)
        else:
            raise AssertionError("unfinished manifest was accepted")
        try:
            worker.verify_frozen_manifest(path, "0" * 64)
        except RuntimeError as exc:
            assert "MANIFEST_HASH_MISMATCH" in str(exc)
        else:
            raise AssertionError("manifest identity change was accepted")
    _synthetic_seal_report()
    print("SYNTHETIC_R1_TEST_WORKER_PASS")


if __name__ == "__main__":
    main()
