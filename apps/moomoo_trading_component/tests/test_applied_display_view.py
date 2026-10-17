from copy import deepcopy
import http.client
import json
from types import SimpleNamespace
import threading

from moomoo_component.server import LocalServer, applied_display_view, _APPLIED_VIEW_MAX_BYTES


def fixture():
    source = {"path": "D:/qualified/input.parquet", "sha256": "a" * 64,
              "inputs": [{"path": "D:/raw/old.csv", "sha256": "b" * 64}] * 1000}
    plan = {"strategy_id": "R7_GROSS_LINEAR", "signal_date": "2026-01-07", "status": "READY",
            "rows": [{"ticker": "SYN_A", "target_weight": .5, "exact_hold_units": 3}],
            "target_cash_weight": .5, "model_fit_calls": 0, "broker_action_allowed": False,
            "source_refs": {"current/input": source}, "requested_gross": .5}
    book = {"strategy_id": "R7_GROSS_LINEAR", "account_id": "original-book", "plan": plan,
            "positions": [{"code": "US.SYN_A", "qty": 3}], "status": "WAITING_OPEN",
            "nav_history": [{"date": "2026-01-07", "nav": 1}], "trades": [{"qty": 3, "source_plan_sha256": "e" * 64, "signal_source_refs": {"old": source}}] * 100,
            "plan_metadata": {"signal_date": "2026-01-07", "source_refs": {"old": source}},
            "close_state": {"huge_audit": [source] * 10}}
    return {"running": True, "status": "WAITING_OPEN", "source_refs": {"current": source},
            "paper_reset": {"preserved_old_state": [source] * 20},
            "book_plan_metadata": {"R7_GROSS_LINEAR": book["plan_metadata"]},
            "books": {"R7_GROSS_LINEAR": book}, "legacy_history": {"books": {"HGB_FACTOR_5": book}},
            "broker": {"strategy_id": "R7_GROSS_LINEAR", "environment": "SIMULATE",
                       "positions": {"US.SYN_A": {"qty": 3}}, "plan": plan,
                       "budget": 10000, "strategy_binding_precondition_sha256": "c" * 64},
            "membership_precondition_sha256": "d" * 64,
            "automatic_completion_policy": {"active_strategy_ids": ["HGB_DIAG_5"], "enabled": True}}


def test_projection_preserves_actual_targets_positions_and_legacy_without_mutation():
    value = fixture(); original = deepcopy(value)
    projected = applied_display_view(value)
    assert value == original
    assert projected["books"]["R7_GROSS_LINEAR"]["plan"]["rows"] == value["books"]["R7_GROSS_LINEAR"]["plan"]["rows"]
    from moomoo_component.best_broker import BestBroker
    assert projected["books"]["R7_GROSS_LINEAR"]["published_target_sha256"] == BestBroker._content_sha(value["books"]["R7_GROSS_LINEAR"]["plan"])
    assert projected["books"]["R7_GROSS_LINEAR"]["published_target_sha256"] != BestBroker._content_sha(projected["books"]["R7_GROSS_LINEAR"]["plan"])
    assert projected["broker"]["positions"] == value["broker"]["positions"]
    assert projected["broker"]["budget"] == 10000
    assert projected["legacy_history"]["books"]["HGB_FACTOR_5"]["positions"]
    assert projected["automatic_completion_policy"] == value["automatic_completion_policy"]
    assert projected["membership_precondition_sha256"] == "d" * 64
    assert "signal_source_refs" not in projected["books"]["R7_GROSS_LINEAR"]["trades"][0]
    assert len(json.dumps(projected).encode()) < 40000 < _APPLIED_VIEW_MAX_BYTES
    assert "paper_reset" not in projected
    assert projected["source_refs"]["current"] == {"path": "D:/qualified/input.parquet", "sha256": "a" * 64}


def test_view_http_is_read_only_and_full_state_remains_available():
    value = fixture(); calls = []
    def state(*, compact=False):
        calls.append(compact)
        return applied_display_view(value) if compact else value
    server = LocalServer(0, None, live=SimpleNamespace(), cohort=SimpleNamespace(state=state))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request("GET", "/api/applied/view")
        response = connection.getresponse(); assert response.status == 200
        assert int(response.getheader("Content-Length")) < 40000
        view = json.loads(response.read())["data"]
        assert view["running"] is True and view["broker"]["environment"] == "SIMULATE"
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request("GET", "/api/applied/state")
        response = connection.getresponse(); assert response.status == 200
        assert json.loads(response.read())["data"]["paper_reset"] == value["paper_reset"]
        connection.close()
        assert calls == [True, False]
    finally:
        server.shutdown(); server.server_close(); thread.join(2)


def test_busy_generation_uses_only_last_immutable_json_and_failures_never_replace_it():
    import time
    from unittest.mock import patch
    value=fixture();calls=[]
    def state(*,compact=False):calls.append(compact);return applied_display_view(value)
    server=LocalServer(0,None,live=SimpleNamespace(),cohort=SimpleNamespace(state=state))
    try:
        fresh=json.loads(server.applied_view_body());saved=server._applied_view_snapshot
        assert fresh["display"]["status"]=="CURRENT"
        server._applied_view_lock.acquire()
        try:
            start=time.monotonic();stale=json.loads(server.applied_view_body())
            assert time.monotonic()-start<.5
            assert stale["display"]["status"]=="STALE" and stale["data"]==fresh["data"]
            assert stale["display"]["captured_at_utc"]==fresh["display"]["captured_at_utc"]
            stale["data"]["books"].clear();assert json.loads(saved[0])["books"]
            assert calls==[True]
        finally:server._applied_view_lock.release()
        with patch.object(server.cohort,"state",side_effect=ValueError("BAD_METADATA")):
            try:server.applied_view_body()
            except ValueError:pass
            else:raise AssertionError("bad owner value was hidden by a cache")
        assert server._applied_view_snapshot is saved
        with patch.object(server.cohort,"state",return_value={"too_large":"x"*_APPLIED_VIEW_MAX_BYTES}):
            try:server.applied_view_body()
            except ValueError as error:assert str(error)=="APPLIED_DISPLAY_RESPONSE_LIMIT"
            else:raise AssertionError("display limit was ignored")
        assert server._applied_view_snapshot is saved
    finally:server.server_close()
