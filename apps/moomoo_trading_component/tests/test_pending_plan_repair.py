"""Synthetic only: original owners, actual-held valuation, and WAL crash shapes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from moomoo_component.applied_source import DailySource, LEGACY_POLICY, _bytes, _reference, _state
from moomoo_component.best_broker import BestBroker, SID
from moomoo_component.cohort import Cohort, HGB_STRATEGIES
from moomoo_component.core import Engine
from test_applied_broker_sync import AppliedBrokerSyncTests as _ServerFixture

SIGNAL, EXEC = "2026-10-06", "2026-10-07"
CLOSE, OPEN = "2026-10-06T20:00:00+00:00", "2026-10-07T13:30:00+00:00"
NOW = datetime(2026, 10, 7, 1, tzinfo=timezone.utc)


class Source(DailySource):
    def __init__(self, root, local, package):
        self.repo_root = root / "repo"
        self.daily_root = root / "daily"
        self.runtime_root = self.daily_root / "applied/source" / local
        self._read_only_roots = (self.repo_root,)
        self.package = package
        self.root = root
        self.version = 0
        self.calls = []
        self.on_load = None
        self.blocked = False
        self.wrong_policy = False
        self.changed_frozen = False
        self.wrong_calendar = False
        for name in ("calendar", "rules", "report", "selected_report", "features"):
            path = root / name
            if not path.exists():
                path.write_text("synthetic frozen " + name)

    def current(self):
        refs = {"selected/package.json": _reference(self.package), "frozen_calendar": _reference(self.root / "calendar"),
                "session_hours_rules": _reference(self.root / "rules"), "daily/report.json": _reference(self.root / "report"),
                "selected/current_report.json": _reference(self.root / "selected_report"),
                "current/features.parquet": _reference(self.root / "features")}
        if self.wrong_calendar:
            refs["frozen_calendar"] = {"path": str(self.root / "calendar"), "sha256": "f" * 64}
        return dict(status="BLOCKED" if self.blocked else "READY", ready=not self.blocked, source_date=SIGNAL,
            signal_date=SIGNAL, execution_date=EXEC, next_open_utc=OPEN, signal_close_utc=CLOSE,
            next_close_utc="2026-10-07T20:00:00+00:00", data_gaps=[], source_refs=refs,
            model_fit_calls=0, source_hashes={"frozen/model": "b" * 64 if not self.changed_frozen else "d" * 64})

    def _call(self, action, **values):
        self.calls.append((action, deepcopy(values)))
        if action == "status":
            return self.current()
        if action == "close_states":
            result = {}
            for sid, book in values["books"].items():
                equity = book["cash"] + sum(qty * 100 for qty in book["positions"].values())
                result[sid] = dict(weights={code[3:]: qty * 100 / equity for code, qty in book["positions"].items()},
                    cash_weight=book["cash"] / equity, signal_date=values["signal_date"], valuation_basis="SIGNAL_CLOSE",
                    source_refs=self.current()["source_refs"])
            return result
        assert action == "load", "No refresh, fit or network action in this fixture"
        result = self.current()
        result["plans"] = {}
        for sid, state in values["states"].items():
            a, b = ((.1, .3) if self.version else (.2, .1))
            result["plans"][sid] = dict(strategy_id=sid, status="READY", signal_date=SIGNAL,
                source_date=SIGNAL, execution_date=EXEC, valuation_basis="SIGNAL_CLOSE",
                account_basis="USER_SUPPLIED_SIGNAL_CLOSE_STATE", model_fit_calls=0,
                rows=[dict(ticker=t, code="US." + t, security_id=t, target_weight=w,
                           weight_before=state["weights"].get(t, 0)) for t, w in (("AAA", a), ("BBB", b))],
                target_cash_weight=1-a-b)
            if self.wrong_policy:
                result["plans"][sid]["policy_id"] = "HGB_TOP20_RISK_R1"
        if self.on_load:
            self.on_load()
        return result


class FundsOnlyBroker:
    account_id = "3604"

    def __init__(self):
        self.cash, self.positions, self.open_orders = 998000.0, {"US.AAA": {"qty": 20}}, []
        self.calls = []

    def snapshot(self, codes, *, include_quotes=True):
        self.calls.append((codes, include_quotes))
        assert codes == [] and include_quotes is False
        return dict(cash=self.cash, equity=self.cash + 2000, positions=deepcopy(self.positions),
                    funds_only=True, quotes={}, open_orders=deepcopy(self.open_orders))

    def close(self):
        pass


class Setup:
    def __init__(self, root):
        self.root = root
        package = root / "package.json"
        package.write_text("synthetic original legacy6")
        self.local, self.remote = Source(root, "local", package), Source(root, "moomoo", package)
        applied = root / "daily/applied"
        self.c = Cohort(applied / "books", self.local, SimpleNamespace(quotes=Mock()),
            execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        self.c.meta["active_strategy_ids"] = list(HGB_STRATEGIES)
        for sid in HGB_STRATEGIES:
            self.c.engines[sid]._set("paper", dict(cash=8000.0, positions={"US.AAA": 20}, fees=1.0))
        self.e = Engine(applied / "moomoo-best")
        self.b = BestBroker(applied / "moomoo-best", self.remote, engine=self.e,
            execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        self.c.best_broker = self.b
        self.e.mode, self.e.account_id, self.e.broker = "moomoo_simulate", "3604", FundsOnlyBroker()
        self.e._set("best_account", "3604")
        self.e._set("best_capital", dict(account_id="3604", budget=10000.0, unused_cash=990000.0))
        self.e.db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("old", "2026-10-05T14:00:00+00:00", SID, "moomoo_simulate", "3604", "US.AAA", "BUY", 20, 100.0,
             "FILLED_ALL", "original", "MARKET"))
        self.e.db.execute("INSERT INTO order_fills VALUES (?,?)", ("old", json.dumps(dict(fill_qty=20,fill_price=100,
            filled_at="2026-10-05T14:00:01+00:00"))))
        self.e.db.commit()
        self.e._set("best_execution", dict(signal_date="2026-10-05", execution_date=SIGNAL, phase="BUY"))
        states = self.local.close_states(self.c._books_input(), SIGNAL)
        old = self.local.load(states, now=NOW)
        self.c.plans, self.c.close_states = old["plans"], states
        self.c.plan_metadata = {k: deepcopy(v) for k,v in old.items() if k != "plans"}
        self.c.plan_metadata.update(execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        self.c._persist()
        remote_states = self.remote.close_states({SID: dict(cash=8000, positions={"US.AAA":20})}, SIGNAL)
        loaded = self.remote.load(remote_states, now=NOW)
        self.saved = dict(plan=loaded["plans"][SID], metadata={k:deepcopy(v) for k,v in loaded.items() if k != "plans"},
                          close_state=remote_states[SID])
        self.e._set("best_plan", self.saved)
        self.b.plan, self.b.metadata = deepcopy(self.saved["plan"]), deepcopy(self.saved["metadata"])
        self.old_archives = [deepcopy(old["archive"]), deepcopy(loaded["archive"])]
        self.before = self.bindings()
        package.write_text("synthetic routing repaired legacy6")
        self.local.version = self.remote.version = 1
        self.sha = _reference(package)["sha256"]
        self.local.calls, self.remote.calls = [], []

    def bindings(self):
        return dict(cohort=json.loads(self.c.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0]),
                    broker=self.e._get("best_plan", None))

    def history(self):
        result = {}
        for name, engine in [("broker",self.e), *self.c.engines.items()]:
            result[name] = {table:[tuple(row) for row in engine.db.execute("SELECT * FROM " + table)]
                for table in ("orders","order_fills","paper_batches","paper_fills","paper_nav")}
            result[name]["paper"] = engine._get("paper", None)
        result["execution"] = self.e._get("best_execution", None)
        result["capital"] = self.e._get("best_capital", None)
        return result

    def close(self):
        self.c.close()


@pytest.fixture
def setup(tmp_path):
    value = Setup(tmp_path)
    try:
        yield value
    finally:
        value.close()


def test_actual_held_repair_preserves_all_history_archives_and_is_idempotent(setup):
    x=setup
    history=x.history()
    x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    assert x.bindings()!=x.before
    assert x.history()==history
    assert all(Path(ref["path"]).read_bytes() and _reference(ref["path"])["sha256"]==ref["sha256"] for ref in x.old_archives)
    for source in (x.local,x.remote):
        closes=[v for action,v in source.calls if action=="close_states"]
        assert closes and all(book["cash"]==8000 and book["positions"]=={"US.AAA":20}
                              for v in closes for book in v["books"].values())
        assert all(action in {"status","load","close_states"} for action,v in source.calls)
    marker=x.e._get("pending_plan_repair",{})
    assert marker["phase"]=="COMMITTED" and marker["order_submissions"]==0
    assert "pending_repairs" in marker["paper_archive"]["path"]
    assert "pending_repairs" in marker["broker_archive"]["path"]
    assert x.c.plans[SID]["rows"][0]["weight_before"]==.2
    assert x.c.plans[SID]["rows"][0]["target_weight"]==.1
    assert x.c.stop_event.is_set() and x.b.stop_event.is_set()
    x.c._pending_repair_guard();x.b._pending_repair_guard()
    calls=len(x.local.calls)+len(x.remote.calls)
    x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    assert len(x.local.calls)+len(x.remote.calls)==calls
    assert x.history()==history


@pytest.mark.parametrize("change",["cohort_running","paper_worker","broker_worker","engine_worker","halt","active_raw",
    "window","paper_account","broker_account","broker_connection_account","budget","pending","current_execution","paper_batch","paper_fill",
    "paper_progress","paper_catchup","broker_catchup","cancelled_order","current_fill","direct","reset","after_open",
    "blocked","calendar","sha","frozen","paper_cash","broker_cash","broker_positions","open_order","broker_fail"])
def test_repair_rejects_unsafe_state_and_keeps_original_plans(setup,change):
    x=setup; now=NOW
    alive=SimpleNamespace(is_alive=lambda:True)
    if change=="cohort_running":x.c.stop_event.clear()
    elif change=="paper_worker":x.c.worker=alive
    elif change=="broker_worker":x.b.worker=alive
    elif change=="engine_worker":x.e.worker=alive
    elif change=="halt":x.c.halt_event.set()
    elif change=="active_raw":x.c.meta["active_strategy_ids"]=["RAW_A2",*HGB_STRATEGIES]
    elif change=="window":x.b.execution_window_seconds=599
    elif change=="paper_account":x.c.engines[SID].account_id="other"
    elif change=="broker_account":x.e.account_id="other"
    elif change=="broker_connection_account":x.e.broker.account_id="other"
    elif change=="budget":x.e._set("best_capital",dict(account_id="3604",budget=1,unused_cash=990000))
    elif change=="pending":x.e.db.execute("UPDATE orders SET status='UNKNOWN'");x.e.db.commit()
    elif change=="current_execution":x.e._set("best_execution",dict(signal_date=SIGNAL,phase="BUY"))
    elif change in {"paper_batch","paper_fill"}:
        table="paper_batches" if change=="paper_batch" else "paper_fills"
        x.c.engines[SID].db.execute("INSERT INTO "+table+" VALUES (?,?)",("current",json.dumps(dict(signal_date=SIGNAL, filled_at=CLOSE, strategy_id=SID, sequence=1))));x.c.engines[SID].db.commit()
    elif change=="paper_progress":x.c.book_status[SID]=dict(execution_date=EXEC,status="WAITING",processed_codes=["US.AAA"])
    elif change=="paper_catchup":x.c.meta["paper_same_day_catchup"]=dict(execution_date=EXEC)
    elif change=="broker_catchup":x.e._set("best_same_day_catchup",dict(execution_date=EXEC))
    elif change=="cancelled_order":x.e.db.execute("UPDATE orders SET created_at=?,status='CANCELLED_BEFORE_SEND'",(CLOSE,));x.e.db.commit()
    elif change=="current_fill":x.e.db.execute("UPDATE order_fills SET payload=?",(json.dumps(dict(fill_qty=20,fill_price=100,filled_at=CLOSE)),));x.e.db.commit()
    elif change=="direct":x.local.wrong_policy=True
    elif change=="reset":x.e._set("best_full_liquidation_reset",dict(stage="PREPARED"))
    elif change=="after_open":now=datetime.fromisoformat(OPEN)
    elif change=="blocked":x.local.blocked=True
    elif change=="calendar":x.local.wrong_calendar=True
    elif change=="sha":x.sha="a"*64
    elif change=="frozen":x.local.changed_frozen=True
    elif change=="paper_cash":x.c.engines[SID]._set("paper",dict(cash=8001,positions={"US.AAA":20}))
    elif change=="broker_cash":x.e.broker.cash+=1
    elif change=="broker_positions":x.e.broker.positions["US.AAA"]["qty"]+=1
    elif change=="open_order":x.e.broker.open_orders=[{"id":"external"}]
    elif change=="broker_fail":x.remote._call=Mock(side_effect=ValueError("SOURCE_COMPUTE_FAILED"))
    with pytest.raises((ValueError,KeyError)):
        x.c.repair_pending_targets("routing6",x.sha,now=now)
    assert x.bindings()==x.before
    x.c.worker=x.b.worker=x.e.worker=None
    x.c.stop_event.set()


def test_failure_after_both_candidates_rolls_back_durable_and_memory(setup):
    x=setup;history=x.history();original=x.c._pending_repair_sql
    def fail_after_write(c,b,m):
        original(c,b,m)
        if m and m.get("phase")=="PREPARED":
            raise RuntimeError("simulated post-write readback failure")
    with patch.object(x.c,"_pending_repair_sql",side_effect=fail_after_write):
        with pytest.raises(RuntimeError):x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    assert x.bindings()==x.before and x.history()==history
    assert x.c.plans==x.before["cohort"]["plans"] and x.b.plan==x.before["broker"]["plan"]
    x.c._pending_repair_guard();x.b._pending_repair_guard()


@pytest.mark.parametrize("shape",["paper_only_prepared","broker_only_prepared","both_prepared","paper_committed_only",
    "broker_committed_only","mixed_plan_durable","committed_missing_peer","tampered_new_plan"])
def test_partial_durable_crash_shapes_fail_closed_for_all_start_and_tick(setup,shape):
    x=setup
    x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    marker=x.e._get("pending_plan_repair",{})
    own,peer=deepcopy(marker),deepcopy(marker)
    if shape=="paper_only_prepared":own["phase"]="PREPARED";peer=None
    elif shape=="broker_only_prepared":own=None;peer["phase"]="PREPARED"
    elif shape in {"both_prepared","mixed_plan_durable"}:own["phase"]=peer["phase"]="PREPARED"
    elif shape=="paper_committed_only":peer["phase"]="PREPARED"
    elif shape=="broker_committed_only":own["phase"]="PREPARED"
    elif shape=="committed_missing_peer":peer=None
    x.c.db.execute("INSERT OR REPLACE INTO settings VALUES ('pending_plan_repair',?)",(json.dumps(own),));x.c.db.commit()
    x.e._set("pending_plan_repair",peer)
    if shape=="mixed_plan_durable":x.e._set("best_plan",marker["previous_broker"])
    if shape=="tampered_new_plan":
        saved=x.e._get("best_plan",{});saved["plan"]["target_cash_weight"]+=.1;x.e._set("best_plan",saved)
    x.b._connect=Mock(side_effect=AssertionError("No connect while crash marker"))
    for call in (x.c.start,x.b.start,lambda:x.c.tick(NOW),lambda:x.b.tick(NOW)):
        with pytest.raises(ValueError):call()
    x.b._connect.assert_not_called()


def test_same_request_recovers_recognised_crash_then_recomputes_from_actual_books(setup):
    x=setup;history=x.history()
    x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    marker=x.e._get("pending_plan_repair",{});marker["phase"]="PREPARED"
    x.c.db.execute("INSERT OR REPLACE INTO settings VALUES ('pending_plan_repair',?)",(json.dumps(marker),));x.c.db.commit()
    x.e._set("pending_plan_repair",marker)
    x.e._set("best_plan",marker["previous_broker"])
    x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    assert x.e._get("pending_plan_repair",{})["phase"]=="COMMITTED"
    assert x.history()==history
    x.c._pending_repair_guard();x.b._pending_repair_guard()


def test_clock_crossing_open_during_compute_is_rejected(setup):
    x=setup
    times=iter([0])
    with patch("moomoo_component.cohort.time.monotonic",side_effect=lambda:next(times,50000)):
        with pytest.raises(ValueError):x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    assert x.bindings()==x.before


def test_clock_crossing_open_during_durable_commit_rolls_back(setup):
    x=setup;crossed=[False];original=x.c._pending_repair_sql
    def write(c,b,m):
        original(c,b,m)
        if m and m["phase"]=="PREPARED":crossed[0]=True
    with patch("moomoo_component.cohort.time.monotonic",side_effect=lambda:50000 if crossed[0] else 0), patch.object(x.c,"_pending_repair_sql",side_effect=write):
        with pytest.raises(ValueError):x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    assert x.bindings()==x.before
    x.c._pending_repair_guard();x.b._pending_repair_guard()


def test_source_changing_again_during_compute_is_rejected(setup):
    x=setup
    x.remote.on_load=lambda:x.local.package.write_text("third source not requested")
    with pytest.raises(ValueError):x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    assert x.bindings()==x.before


def test_same_signal_prepare_reuses_committed_archive_after_restart_without_load(setup):
    x=setup
    x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    before=x.bindings();history=x.history()
    with patch.object(x.local,"load",side_effect=AssertionError("No normal archive collision")), patch.object(x.remote,"load",side_effect=AssertionError("No broker reload")):
        x.c._prepare(x.local.status(now=NOW),NOW)
        x.b.stop_event.clear();x.b._prepare(NOW);x.b.stop_event.set()
        assert x.bindings()==before
        x.c.close()
        x.c=Cohort(x.root / "daily/applied/books",x.local,SimpleNamespace(quotes=Mock()),
            execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
        x.e=Engine(x.root / "daily/applied/moomoo-best")
        x.b=BestBroker(x.root / "daily/applied/moomoo-best",x.remote,engine=x.e,
            execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
        x.c.best_broker=x.b
        x.c._prepare(x.local.status(now=NOW),NOW)
        x.b.stop_event.clear();x.b._prepare(NOW);x.b.stop_event.set()
        x.c._pending_repair_guard();x.b._pending_repair_guard()
        assert x.c.plans==before["cohort"]["plans"] and x.e._get("best_plan",{})==before["broker"]
        assert x.history()==history


def test_next_signal_uses_original_load_then_can_repair_its_own_archive(setup):
    x=setup
    x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    next_now=datetime(2026,10,7,21,tzinfo=timezone.utc)
    x.local.package.write_text("synthetic normal legacy signal7")
    for source in (x.local,x.remote):
        original_current=source.current
        def current(original=original_current):
            return {**original(), "signal_date":EXEC, "source_date":EXEC, "execution_date":"2026-10-08",
                "signal_close_utc":"2026-10-07T20:00:00+00:00", "next_open_utc":"2026-10-08T13:30:00+00:00",
                "next_close_utc":"2026-10-08T20:00:00+00:00"}
        source.current=current
        original_call=source._call
        def call(action, original=original_call, **values):
            result=original(action,**values)
            if action=="load":
                for plan in result["plans"].values():plan.update(signal_date=EXEC,source_date=EXEC,execution_date="2026-10-08")
            return result
        source._call=call
    with patch.object(x.local,"load",wraps=x.local.load) as paper_load,patch.object(x.remote,"load",wraps=x.remote.load) as broker_load:
        x.c._prepare(x.local.status(now=next_now),next_now)
        x.b.snapshot=x.e.broker.snapshot([],include_quotes=False)
        x.b.stop_event.clear();x.b._prepare(next_now);x.b.stop_event.set()
        assert paper_load.call_count==broker_load.call_count==1
        assert "repair_request" not in paper_load.call_args.kwargs
        assert "repair_request" not in broker_load.call_args.kwargs
    assert (x.local.runtime_root/EXEC/"plans.json").is_file()
    assert (x.remote.runtime_root/EXEC/"plans.json").is_file()
    x.local.package.write_text("synthetic routing repaired legacy signal7")
    sha=_reference(x.local.package)["sha256"]
    x.c.repair_pending_targets("routing7",sha,now=next_now)
    marker=x.e._get("pending_plan_repair",{})
    assert marker["signal_date"]==EXEC and marker["previous_marker"]["signal_date"]==SIGNAL
    assert Path(marker["previous_paper_archive"]["path"])==x.local.runtime_root/EXEC/"plans.json"
    x.c._pending_repair_guard();x.b._pending_repair_guard()


def test_committed_same_signal_prepare_refuses_new_unbound_source(setup):
    x=setup;x.c.repair_pending_targets("routing6",x.sha,now=NOW)
    x.local.package.write_text("a later unapproved source")
    with pytest.raises(ValueError):x.c._prepare(x.local.status(now=NOW),NOW)
    x.b.stop_event.clear()
    try:
        with pytest.raises(ValueError):x.b._prepare(NOW)
    finally:x.b.stop_event.set()


class TestPendingRepairServer(unittest.TestCase):
    setUp = _ServerFixture.setUp
    tearDown = _ServerFixture.tearDown
    post = _ServerFixture.post

    def test_fixed_route_calls_coordinator_once_with_server_clock(self):
        self.cohort.repair_pending_targets=Mock(return_value={"running":False})
        code,result=self.post({"repair_id":"routing6","expected_package_sha256":"a"*64},path="/api/applied/repair-pending-targets")
        assert code==200 and result["data"]["running"] is False
        args,kw=self.cohort.repair_pending_targets.call_args
        assert args==("routing6","a"*64) and kw["now"].tzinfo is not None
        self.manual.reconcile.assert_not_called();self.best.reconcile.assert_not_called()

    def test_fixed_route_rejects_overrides_and_bad_csrf(self):
        self.cohort.repair_pending_targets=Mock()
        body={"repair_id":"routing6","expected_package_sha256":"a"*64}
        for extra in ({"now":OPEN},{"account_id":"x"},{"window":3600},{"policy_id":"HGB_TOP20_RISK_R1"},{"start":True}):
            code,result=self.post({**body,**extra},path="/api/applied/repair-pending-targets")
            assert code==400 and result["ok"] is False
        code,result=self.post(body,token="bad",path="/api/applied/repair-pending-targets")
        assert code==403
        self.cohort.repair_pending_targets.assert_not_called()


del _ServerFixture


def _synthetic_committed_z_clock(x):
    from moomoo_component.applied_source import _pending_plan_digest
    x.c.repair_pending_targets("clock_compatibility", x.sha, now=NOW)
    value = json.loads(x.c.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
    value["plan_metadata"]["next_open_utc"] = OPEN.replace("+00:00", "Z")
    value["plan_metadata"]["execution_time_utc"] = OPEN.replace("+00:00", "Z")
    marker = x.e._get("pending_plan_repair", {})
    marker["new_hashes"]["cohort"] = _pending_plan_digest(value, "cohort")
    x.c.db.execute("INSERT OR REPLACE INTO settings VALUES ('pending_plan_repair',?)", (json.dumps(marker),))
    x.e._set("pending_plan_repair", marker)
    x.c.db.execute("INSERT OR REPLACE INTO settings VALUES ('cohort',?)", (json.dumps(value),))
    x.c.db.commit()
    x.c._pending_repair_guard()
    value["plan_metadata"]["execution_time_utc"] = OPEN
    return value


def test_committed_clock_spelling_only_matches_complete_original_plan_hash(setup):
    x = setup
    value = _synthetic_committed_z_clock(x)
    old_markers = x.e._get("pending_plan_repair", {})
    x.c.db.execute("UPDATE settings SET value=? WHERE key='cohort'", (json.dumps(value),))
    x.c.db.commit()
    x.c._pending_repair_guard()
    x.b._pending_repair_guard()
    assert x.e._get("pending_plan_repair", {}) == old_markers
    assert json.loads(x.c.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0]) == value


@pytest.mark.parametrize("change", ["time", "plan", "close_state", "refs", "window", "delay", "partial", "peer", "phase"])
def test_clock_spelling_compatibility_cannot_accept_any_other_binding_change(setup, change):
    x = setup
    value = _synthetic_committed_z_clock(x)
    meta = value["plan_metadata"]
    if change == "time": meta["execution_time_utc"] = "2026-10-07T13:30:01+00:00"
    elif change == "plan": value["plans"][SID]["target_cash_weight"] += .01
    elif change == "close_state": value["plan_close_states"][SID]["cash_weight"] += .01
    elif change == "refs": meta["source_refs"]["daily/report.json"]["sha256"] = "f" * 64
    elif change == "window": meta["execution_window_seconds"] = 601
    elif change == "delay": meta["execution_delay_minutes"] = 1
    elif change == "partial": meta["allow_partial_quotes"] = False
    elif change in {"peer", "phase"}:
        marker = x.e._get("pending_plan_repair", {})
        marker["phase"] = "PREPARED"
        x.e._set("pending_plan_repair", marker)
        if change == "phase":
            x.c.db.execute("UPDATE settings SET value=? WHERE key='pending_plan_repair'", (json.dumps(marker),))
    x.c.db.execute("UPDATE settings SET value=? WHERE key='cohort'", (json.dumps(value),))
    x.c.db.commit()
    with pytest.raises(ValueError): x.c._pending_repair_guard()
    with pytest.raises(ValueError): x.b._pending_repair_guard()
