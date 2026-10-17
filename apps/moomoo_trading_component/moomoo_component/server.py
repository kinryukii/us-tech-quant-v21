"""Loopback-only dashboard. JSON + per-process CSRF token protect mutations."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from copy import deepcopy
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

from .core import Engine

FRAME_ORIGINS = tuple(f"http://{host}:{port}" for host in ("127.0.0.1", "localhost")
                      for port in (8501, 8506, 8507, 8516))
LIVE_READ_ENDPOINTS = frozenset({"/api/live/connect", "/api/live/select", "/api/live/refresh"})


_APPLIED_VIEW_MAX_BYTES = 4 * 1024 * 1024
_APPLIED_VIEW_LOCK_TIMEOUT_SECONDS = .1
_APPLIED_DISPLAY_OMITTED_RECORD_FIELDS = frozenset({
    "close_state", "preserved_settings", "preserved_cohort_setting", "full_liquidation_reset",
    "paper_target_revision_history", "signal_source_refs", "source_plan"})


def applied_display_view(state):
    """Project display records; full provenance/history stays in the owner/DB."""
    def refs(value):
        return {key: {name: leaf[name] for name in ("path", "sha256") if name in leaf}
                for key, leaf in (value or {}).items() if isinstance(leaf, dict)}

    def record(value):
        if isinstance(value, list):
            return [record(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {key: refs(item) if key in {"source_refs", "model_refs"} else record(item)
                for key, item in value.items()
                if key not in _APPLIED_DISPLAY_OMITTED_RECORD_FIELDS}

    def book(value):
        result = record({key: item for key, item in value.items() if key != "plan_metadata"})
        plan = value.get("plan")
        if isinstance(plan, dict):
            from .best_broker import BestBroker
            result["published_target_sha256"] = BestBroker._content_sha(plan)
        metadata = value.get("plan_metadata") or {}
        result["plan_metadata"] = {key: item for key, item in metadata.items()
            if item is None or isinstance(item, (str, int, float, bool))}
        return result

    complex_keys = {"automatic_completion_policy", "subscription_prewarm", "book_quote_asof",
                    "book_quote_errors", "book_valuation", "paper_same_day_catchup",
                    "execution_charts_update", "strategies", "trades", "broker", "next_ordinary_execution_clock",
                    "showcase_ids", "roster_ref", "showcase_roster_binding", "inactive_queryable_ids"}
    result = {key: record(item) for key, item in state.items()
        if key in complex_keys or item is None or isinstance(item, (str, int, float, bool))}
    result["books"] = {sid: book(value) for sid, value in state.get("books", {}).items()}
    result["legacy_history"] = {"books": {sid: book(value) for sid, value in
        state.get("legacy_history", {}).get("books", {}).items()}}
    result["source_refs"] = refs(state.get("source_refs"))
    binding = state.get("strategy_membership_binding") or {}
    result["strategy_membership_binding"] = {key: record(item) for key, item in binding.items()
        if item is None or isinstance(item, (str, int, float, bool))
        or key in {"active_strategy_ids", "previous_active_strategy_ids", "retained_legacy_strategy_ids"}}
    return result


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, engine, live=None, cohort=None):
        self.engine = engine
        self.cohort = cohort
        broker = getattr(cohort,"best_broker",None)
        if broker is not None:
            owner = getattr(broker,"_maintenance_owner",None)
            if owner is not None and owner is not cohort:
                raise ValueError("APPLIED_BROKER_CANONICAL_OWNER_CONFLICT")
            broker._maintenance_owner = cohort
        self._applied_view_lock = threading.Lock()
        self._applied_view_snapshot = None  # One immutable, presentation-only JSON copy.
        self.token = secrets.token_urlsafe(32)
        self.live_token = secrets.token_urlsafe(32)
        if live is None:
            from .live import LiveReadOnly
            live = LiveReadOnly()
        self.live = live
        super().__init__(("127.0.0.1", port), Handler)


    @staticmethod
    def _view_body(data, captured, *, stale):
        display = dict(status="STALE" if stale else "CURRENT", captured_at_utc=captured,
            served_at_utc=datetime.now(timezone.utc).isoformat(), owner_busy=stale)
        return (b'{"ok":true,"data":' + data + b',"display":' +
            json.dumps(display, ensure_ascii=False, allow_nan=False).encode("utf-8") + b'}')

    def _last_applied_view(self):
        snapshot = self._applied_view_snapshot
        if snapshot is None:
            raise TimeoutError("APPLIED_DISPLAY_OWNER_BUSY")
        return self._view_body(*snapshot, stale=True)

    def applied_view_body(self):
        # No mutation, plan, funds, authorization or precondition path reads this cache.
        if not self._applied_view_lock.acquire(timeout=_APPLIED_VIEW_LOCK_TIMEOUT_SECONDS):
            return self._last_applied_view()
        try:
            try:
                reader = getattr(self.cohort, "display_state", None)
                value = (reader(lock_timeout_seconds=_APPLIED_VIEW_LOCK_TIMEOUT_SECONDS)
                    if callable(reader) else self.cohort.state(compact=True))
            except TimeoutError:
                return self._last_applied_view()
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            captured = datetime.now(timezone.utc).isoformat()
            body = self._view_body(data, captured, stale=False)
            if len(body) > _APPLIED_VIEW_MAX_BYTES:
                raise ValueError("APPLIED_DISPLAY_RESPONSE_LIMIT")
            self._applied_view_snapshot = (data, captured)
            return body
        finally:
            self._applied_view_lock.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "MoomooSimulation/0.1"

    def log_message(self, fmt, *args):
        pass  # No request payloads / account IDs in access logs.

    def _host_ok(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def _reply(self, code, body, mime="application/json; charset=utf-8", *, embeddable=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if not embeddable:
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        ancestors = "'self' " + " ".join(FRAME_ORIGINS) if embeddable else "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors {ancestors}; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return self._reply(403, {"ok": False, "error": "仅允许本机访问"})
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self._reply(200, {"ok": True, "data": {"component": "moomoo-trading-component", "api_version": 1,
                "live_execution_enabled": False, "pages": ["paper", "live"],
                "manual_data_updates": getattr(self.server.cohort, "manual_data_updates", False)}})
        if path == "/api/token":
            return self._reply(200, {"ok": True, "data": {"token": self.server.token}})
        if path == "/api/live/token":
            return self._reply(200, {"ok": True, "data": {"token": self.server.live_token}})
        if path == "/api/live/state":
            return self._reply(200, {"ok": True, "data": self.server.live.state()})
        if path == "/api/state":
            return self._reply(200, {"ok": True, "data": self.server.engine.state()})
        if path == "/api/applied/broker-native-reset-precondition":
            broker = getattr(self.server.cohort,"best_broker",None)
            if broker is None:
                return self._reply(503, {"ok":False,"error":"APPLIED_BROKER_OWNER_UNAVAILABLE"})
            try:
                return self._reply(200, {"ok":True,"data":broker.native_reset_precondition()})
            except Exception as exc:
                return self._reply(409, {"ok":False,"error":str(exc)})
        if path == "/api/applied/maintenance-status":
            if self.server.cohort is None:
                return self._reply(503, {"ok": False, "error": "APPLIED_OWNER_UNAVAILABLE"})
            return self._reply(200, {"ok": True, "data": self.server.cohort.maintenance_status()})
        if path == "/api/applied/showcase-roster":
            if self.server.cohort is None:
                return self._reply(503, {"ok": False, "error": "APPLIED_OWNER_UNAVAILABLE"})
            try:
                result = self.server.cohort.showcase_roster_state()
                body = json.dumps({"ok": True, "data": result}, ensure_ascii=False, allow_nan=False).encode("utf-8")
                if len(body) > 65536:
                    return self._reply(503, {"ok": False, "error": "SHOWCASE_ROSTER_METADATA_RESPONSE_LIMIT"})
            except Exception as exc:
                return self._reply(503, {"ok": False, "error": "SHOWCASE_ROSTER_METADATA_UNAVAILABLE",
                    "error_type": type(exc).__name__})
            return self._reply(200, body)
        if path in {"/api/applied/state", "/api/applied/view"}:
            if self.server.cohort is None:
                return self._reply(503, {"ok": False, "error": "策略纸面账户尚未配置"})
            if path == "/api/applied/state":
                return self._reply(200, {"ok": True, "data": self.server.cohort.state()})
            try:
                body = self.server.applied_view_body()
            except TimeoutError:
                return self._reply(503, {"ok": False, "error": "APPLIED_DISPLAY_OWNER_BUSY", "owner_busy": True})
            except Exception as exc:
                if isinstance(exc, ValueError) and str(exc) == "APPLIED_DISPLAY_RESPONSE_LIMIT":
                    return self._reply(503, {"ok": False, "error": "APPLIED_DISPLAY_RESPONSE_LIMIT"})
                return self._reply(503, {"ok": False, "error": "APPLIED_DISPLAY_UNAVAILABLE", "error_type": type(exc).__name__})
            if len(body) > _APPLIED_VIEW_MAX_BYTES:
                return self._reply(503, {"ok": False, "error": "APPLIED_DISPLAY_RESPONSE_LIMIT"})
            try:
                return self._reply(200, body)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
                return  # A closed read-only tab does not indicate an owner failure.

        if path == "/api/applied/trades.csv":
            if self.server.cohort is None:
                return self._reply(503, {"ok": False, "error": "策略纸面账户尚未配置"})
            fields = ["strategy_id", "account_id", "signal_date", "execution_date", "filled_at",
                      "code", "side", "qty", "fill_price", "fee", "status", "quote_asof", "source", "id"]
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.server.cohort.trades())
            return self._reply(200, ("\ufeff" + stream.getvalue()).encode("utf-8"), "text/csv; charset=utf-8")
        if path == "/static/workspace_theme.css":
            # One fixed UI source asset; request parameters never choose a file.
            theme_path = Path(__file__).resolve().parents[2] / "shared_ui" / "theme.css"
            return self._reply(200, theme_path.read_bytes(), "text/css; charset=utf-8")
        files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
        files["/static/app.js"] = files["/app.js"]
        files["/static/style.css"] = files["/style.css"]
        files["/paper"] = files["/"]
        files["/manual"] = files["/"]
        if self.server.cohort is not None:
            files["/"] = files["/paper"] = ("applied.html", "text/html; charset=utf-8")
        files["/static/applied.js"] = ("applied.js", "text/javascript; charset=utf-8")
        files["/static/applied.css"] = ("applied.css", "text/css; charset=utf-8")
        files["/live"] = ("live.html", "text/html; charset=utf-8")
        files["/static/live.js"] = ("live.js", "text/javascript; charset=utf-8")
        if path in files:
            name, mime = files[path]
            return self._reply(200, (Path(__file__).parent / "static" / name).read_bytes(), mime,
                               embeddable=path in ("/", "/paper", "/manual", "/live"))
        self._reply(404, {"ok": False, "error": "接口不存在"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        expected_origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if not self._host_ok() or (origin and origin not in expected_origins) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._reply(403, {"ok": False, "error": "跨站请求被拒绝"})
        token = self.headers.get("X-CSRF-Token", "")
        path = urlsplit(self.path).path
        is_live = path.startswith("/api/live/")
        if is_live and path not in LIVE_READ_ENDPOINTS:
            return self._reply(403, {"ok": False, "error": "实盘下单、解锁、撤单和自动执行未授权且未实现"})
        expected_token = self.server.live_token if is_live else self.server.token
        if not secrets.compare_digest(token, expected_token):
            return self._reply(403, {"ok": False, "error": "请求令牌失效，请刷新页面"})
        if self.headers.get_content_type() != "application/json":
            return self._reply(415, {"ok": False, "error": "仅接受 JSON"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_048_576 or self.headers.get("Transfer-Encoding"):
                return self._reply(413, {"ok": False, "error": "请求体必须为1字节至1MB"})
            body = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("禁止非有限JSON数字")))
            if not isinstance(body, dict):
                raise ValueError("请求必须是 JSON 对象")
            engine = self.server.engine
            if path.startswith("/api/applied/"):
                if self.server.cohort is None:
                    raise ValueError("策略纸面账户尚未配置")
                if (getattr(self.server.cohort, "_maintenance_active", lambda:False)() and path not in {
                        "/api/applied/maintenance-begin", "/api/applied/maintenance-end",
                        "/api/applied/prepare-current", "/api/applied/charts-update",
                        "/api/applied/stop", "/api/applied/halt", "/api/applied/reconcile"}):
                    raise ValueError("MANUAL_MAINTENANCE_ACTIVE")
                if path in {"/api/applied/maintenance-begin", "/api/applied/maintenance-end"}:
                    allowed = {"maintenance_id"} if path.endswith("maintenance-begin") else {"maintenance_id", "abort"}
                    if not {"maintenance_id"} <= set(body) <= allowed or not isinstance(body["maintenance_id"], str):
                        raise ValueError("MANUAL_MAINTENANCE_EXACT_CONTROL_FIELDS_REQUIRED")
                    action = (self.server.cohort.begin_manual_maintenance if path.endswith("maintenance-begin")
                              else self.server.cohort.end_manual_maintenance)
                    result = action(**body)
                elif path in {"/api/applied/prepare-current", "/api/applied/charts-update"}:
                    allowed = {"expected_signal_date", "maintenance_id"}
                    if path.endswith("charts-update"):
                        allowed.add("finite_ca_admission_ref")
                    if (not {"expected_signal_date"} <= set(body) <= allowed
                            or not isinstance(body["expected_signal_date"], str)
                            or "maintenance_id" in body and not isinstance(body["maintenance_id"], str)):
                        raise ValueError("MANUAL_PUBLISHED_DATE_AND_OWNER_CONTROL_REQUIRED")
                    if "finite_ca_admission_ref" in body:
                        ref = body["finite_ca_admission_ref"]
                        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                                or not isinstance(ref["path"], str) or not ref["path"]
                                or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])):
                            raise ValueError("FINITE_CA_ADMISSION_REFERENCE_REQUIRED")
                    action = (self.server.cohort.prepare_published_inputs if path.endswith("prepare-current")
                              else self.server.cohort.request_execution_charts)
                    result = action(**body, **({} if "maintenance_id" in body else {"now": datetime.now(timezone.utc)}))
                elif path in {"/api/applied/showcase-roster-preview", "/api/applied/showcase-roster"}:
                    fields = {"roster_ref"} if path.endswith("-preview") else {"roster_ref", "expected_precondition_sha256"}
                    if set(body) != fields:
                        raise ValueError("SHOWCASE_ROSTER_EXACT_CONTROL_FIELDS_REQUIRED")
                    action = (self.server.cohort.preview_showcase_roster if path.endswith("-preview")
                              else self.server.cohort.revise_showcase_roster)
                    result = action(**body, now=datetime.now(timezone.utc))
                elif path == "/api/applied/strategy-membership":
                    fields = {"migration_id", "requested_at", "expected_precondition_sha256", "target_strategy_ids"}
                    if set(body) != fields:
                        raise ValueError("策略成员迁移仅接受明确绑定请求")
                    result = self.server.cohort.migrate_strategy_membership(**body, now=datetime.now(timezone.utc))
                elif path == "/api/applied/broker-native-reset-adoption":
                    fields = {"reset_id","requested_at","expected_old_account_id","new_account_id",
                              "target_strategy_id","expected_precondition_sha256","budget"}
                    broker = self.server.cohort.best_broker
                    if set(body) != fields or broker is None:
                        raise ValueError("NATIVE_RESET_EXACT_CONTROL_FIELDS_REQUIRED")
                    result = broker.adopt_native_reset(**body,now=datetime.now(timezone.utc))
                elif path == "/api/applied/broker-strategy-binding":
                    fields = {"binding_id", "requested_at", "expected_strategy_id", "target_strategy_id", "expected_precondition_sha256"}
                    if set(body) != fields or self.server.cohort.best_broker is None:
                        raise ValueError("原模拟策略切换仅接受明确绑定请求")
                    result = self.server.cohort.best_broker.bind_strategy(**body, now=datetime.now(timezone.utc))
                elif path == "/api/applied/broker-published-target-alignment":
                    fields = {"alignment_id", "requested_at", "expected_strategy_id", "signal_date",
                              "expected_target_sha256", "expected_precondition_sha256"}
                    cohort, broker = self.server.cohort, self.server.cohort.best_broker
                    if set(body) != fields or not all(isinstance(value, str) for value in body.values()) or broker is None:
                        raise ValueError("发布目标对齐仅接受当前策略、日期、目标SHA、账户前置SHA及请求身份")
                    with cohort.lock:
                        sid = body["expected_strategy_id"]
                        if sid not in cohort._active_ids():
                            raise ValueError("发布目标必须属于当前活动策略")
                        target = deepcopy(cohort.plans.get(sid))
                        frozen = deepcopy(cohort.meta.get("book_plan_metadata", {}).get(sid, cohort.plan_metadata))
                    broker.align_published_target(**body, published_plan=target, published_metadata=frozen,
                        now=datetime.now(timezone.utc))
                    result = cohort.state(compact=True)
                elif path == "/api/applied/broker-native-manual-completion":
                    fields = {"manual_id", "requested_at", "deadline_utc", "expected_strategy_id", "signal_date",
                        "expected_plan_sha256", "expected_source_sha256", "expected_reset_receipt_sha256", "expected_precondition_sha256"}
                    broker = self.server.cohort.best_broker
                    continuation = body.get("continuation")
                    if (set(body) not in (fields, fields | {"continuation"}) or broker is None
                            or any(not isinstance(body.get(key), str) for key in fields)
                            or "continuation" in body and (not isinstance(continuation, dict)
                                or set(continuation) != {"expected_prior_sha256", "expected_execution_sha256"}
                                or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in continuation.values()))):
                        raise ValueError("NATIVE_MANUAL_EXACT_CONTROL_FIELDS_REQUIRED")
                    result = broker.authorize_native_manual_completion(**body, now=datetime.now(timezone.utc))
                elif path == "/api/applied/broker-published-target-manual-completion":
                    fields = {"manual_id", "requested_at", "deadline_utc", "expected_strategy_id", "signal_date",
                              "expected_target_sha256", "expected_precondition_sha256"}
                    broker = self.server.cohort.best_broker
                    if set(body) != fields or not all(isinstance(value,str) for value in body.values()) or broker is None:
                        raise ValueError("手动补单仅接受当前冻结目标、账户前提与独立有限窗口")
                    broker.authorize_manual_published_completion(**body, now=datetime.now(timezone.utc))
                    result = self.server.cohort.state(compact=True)
                elif path == "/api/applied/broker-published-target-conversion":
                    fields = {"conversion_id", "alignment_id", "requested_at", "expected_precondition_sha256"}
                    broker = self.server.cohort.best_broker
                    if set(body) != fields or not all(isinstance(value, str) for value in body.values()) or broker is None:
                        raise ValueError("统一持仓接续仅接受原对齐身份、请求身份和账户前置SHA")
                    broker.authorize_target_conversion(**body, now=datetime.now(timezone.utc))
                    result = self.server.cohort.state(compact=True)
                elif path == "/api/applied/broker-published-target-alignment-rollback":
                    fields = {"alignment_id", "expected_precondition_sha256"}
                    broker = self.server.cohort.best_broker
                    if set(body) != fields or not all(isinstance(value, str) for value in body.values()) or broker is None:
                        raise ValueError("发布目标回滚仅接受当前对齐身份及账户前置SHA")
                    broker.rollback_published_target_alignment(**body, now=datetime.now(timezone.utc))
                    result = self.server.cohort.state(compact=True)
                elif path == "/api/applied/reset-hgb":
                    required = {"reset_id", "requested_at", "strategy_ids", "signal_date",
                                "expected_policy_id", "expected_package_sha256"}
                    if (set(body) != required or body.get("strategy_ids") != ["HGB_DIAG_5", "HGB_FACTOR_5"]
                            or not all(isinstance(body.get(key), str) for key in required - {"strategy_ids"})
                            or not 1 <= len(body["reset_id"]) <= 64
                            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in body["reset_id"])
                            or body["expected_policy_id"] != "HGB_TOP20_RISK_R1"
                            or len(body["expected_package_sha256"]) != 64
                            or any(char not in "0123456789abcdef" for char in body["expected_package_sha256"])):
                        raise ValueError("HGB重启仅接受固定两策略、成熟信号、活动包SHA和重启身份")
                    broker = self.server.cohort.best_broker
                    if broker is None:
                        raise ValueError("尚未配置原策略券商模拟账户")
                    reset_clock = datetime.now(timezone.utc)
                    broker.prepare_full_liquidation_reset(body, now=reset_clock)
                    result = self.server.cohort.reset_hgb(body, now=reset_clock)
                elif path == "/api/applied/broker-cancel-reset":
                    reset_id = body.get("reset_id")
                    if (set(body) != {"reset_id"} or not isinstance(reset_id, str)
                            or not 1 <= len(reset_id) <= 64
                            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in reset_id)):
                        raise ValueError("取消尚未执行的券商重置仅接受原 reset_id")
                    broker = self.server.cohort.best_broker
                    if broker is None:
                        raise ValueError("尚未配置原策略券商模拟账户")
                    cancel_clock = datetime.now(timezone.utc)
                    broker.cancel_full_liquidation_reset(reset_id, now=cancel_clock)
                    result = broker.prepare_current_target_rebalance(reset_id, now=cancel_clock)
                elif path == "/api/applied/repair-pending-targets":
                    repair_id, package_sha = body.get("repair_id"), body.get("expected_package_sha256")
                    if (set(body) != {"repair_id", "expected_package_sha256"}
                            or not isinstance(repair_id, str) or not 1 <= len(repair_id) <= 64
                            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in repair_id)
                            or not repair_id[0].isalnum()
                            or not isinstance(package_sha, str) or len(package_sha) != 64
                            or any(char not in "0123456789abcdef" for char in package_sha)):
                        raise ValueError("待开盘目标修订仅接受 repair_id 和新活动包 SHA")
                    result = self.server.cohort.repair_pending_targets(
                        repair_id, package_sha, now=datetime.now(timezone.utc))
                elif path in {"/api/applied/broker-revise-target", "/api/applied/revise-targets"}:
                    reset_id, package_sha = body.get("reset_id"), body.get("expected_package_sha256")
                    if (set(body) != {"reset_id", "expected_package_sha256"}
                            or not isinstance(reset_id, str) or not 1 <= len(reset_id) <= 64
                            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in reset_id)
                            or not isinstance(package_sha, str) or len(package_sha) != 64
                            or any(char not in "0123456789abcdef" for char in package_sha)):
                        raise ValueError("同日目标修订仅接受原 reset_id 和新活动包 SHA")
                    broker = self.server.cohort.best_broker
                    if broker is None:
                        raise ValueError("尚未配置原策略券商模拟账户")
                    revision_clock = datetime.now(timezone.utc)
                    if path == "/api/applied/revise-targets":
                        cohort = self.server.cohort
                        if (not cohort.stop_event.is_set() or not broker.stop_event.is_set()
                                or (cohort.worker and cohort.worker.is_alive())
                                or (broker.worker and broker.worker.is_alive())):
                            raise ValueError("同日目标修订要求纸面仓和原券商模拟执行均已停止")
                        cohort.revise_hgb_targets(reset_id, package_sha, now=revision_clock)
                        broker.revise_current_target_rebalance(reset_id, package_sha, now=revision_clock)
                        result = cohort.state()
                    else:
                        result = broker.revise_current_target_rebalance(
                            reset_id, package_sha, now=revision_clock)

                elif path == "/api/applied/automatic-completion-policy":
                    if set(body) != {"enabled", "close_buffer_seconds", "one_tick_spread"}:
                        raise ValueError("自动接续只接受明确启用、收盘缓冲和获准一档价差规则")
                    result = self.server.cohort.authorize_automatic_completion_policy(
                        **body, now=datetime.now(timezone.utc))
                elif path == "/api/applied/broker-manual-residual-sell":
                    required = {"execution_date", "deadline_utc", "authorization_id", "code", "target_qty", "max_sell_qty",
                        "limit_price", "max_spread_bps", "spread_authorization", "expected_prior_sha256",
                        "expected_plan_sha256", "expected_execution_sha256", "expected_package_sha256"}
                    if set(body) != required:
                        raise ValueError("人工剩余卖出仅接受一个冻结目标、原SHA和本次明确单笔授权边界")
                    broker = self.server.cohort.best_broker
                    if broker is None:
                        raise ValueError("尚未配置原策略券商模拟账户")
                    result = broker.authorize_manual_residual_sell(**body, now=datetime.now(timezone.utc))
                elif path in {"/api/applied/broker-manual-residual-sell-execute", "/api/applied/broker-manual-residual-sell-cancel"}:
                    if set(body) != {"authorization_id"} or not isinstance(body["authorization_id"], str):
                        raise ValueError("人工剩余卖出执行/取消仅接受原authorization_id")
                    broker = self.server.cohort.best_broker
                    if broker is None:
                        raise ValueError("尚未配置原策略券商模拟账户")
                    action = broker.execute_manual_residual_sell if path.endswith("-execute") else broker.cancel_manual_residual_sell
                    result = action(body["authorization_id"], now=datetime.now(timezone.utc))
                elif path == "/api/applied/broker-native-first-execution":
                    required={"authorization_id","requested_at","deadline_utc","expected_strategy_id","expected_plan_sha256",
                        "expected_source_sha256","expected_reset_receipt_sha256","expected_precondition_sha256"}
                    if set(body)!=required or any(not isinstance(body[key],str) for key in required):
                        raise ValueError("NATIVE_FIRST_EXECUTION_EXACT_REQUEST_FIELDS_REQUIRED")
                    broker=self.server.cohort.best_broker
                    if broker is None:raise ValueError("NATIVE_FIRST_EXECUTION_BROKER_REQUIRED")
                    result=broker.authorize_native_first_execution(**body,now=datetime.now(timezone.utc))
                elif path in {"/api/applied/first-execution", "/api/applied/broker-first-execution"}:
                    broker_route = path == "/api/applied/broker-first-execution"
                    plan_key = "expected_plan_sha256" if broker_route else "expected_plan_sha256_by_book"
                    required = {"execution_date", "deadline_utc", "authorization_id", "expected_package_sha256", plan_key}
                    plan_hashes = [body.get(plan_key)] if broker_route else list(body.get(plan_key, {}).values()) if isinstance(body.get(plan_key), dict) else []
                    continuation = body.get("continuation")
                    continuation_key = "expected_execution_sha256" if broker_route else "expected_ledger_sha256_by_book"
                    continuation_hashes = []
                    if continuation is not None:
                        if not isinstance(continuation, dict) or set(continuation) != {"expected_prior_sha256", continuation_key}:
                            raise ValueError("续段必须明确绑定原许可和本次原执行状态")
                        value = continuation[continuation_key]
                        if not broker_route and (not isinstance(value, dict) or set(value) != {"HGB_DIAG_5", "HGB_FACTOR_5"}):
                            raise ValueError("纸面续段必须绑定原两本账簿状态")
                        continuation_hashes = [continuation["expected_prior_sha256"], value] if broker_route else [continuation["expected_prior_sha256"], *value.values()]
                    if (set(body) != required | ({"continuation"} if continuation is not None else set())
                            or not all(isinstance(body.get(k), str) for k in required - {plan_key})
                            or not 8 <= len(body["authorization_id"]) <= 80
                            or not all(c.isascii() and (c.isalnum() or c in "_-") for c in body["authorization_id"])
                            or (not broker_route and (not isinstance(body.get(plan_key), dict)
                                or set(body[plan_key]) != {"HGB_DIAG_5", "HGB_FACTOR_5"}))
                            or not plan_hashes or any(not isinstance(v, str) or len(v) != 64
                                or any(c not in "0123456789abcdef" for c in v)
                                for v in [body["expected_package_sha256"], *plan_hashes, *continuation_hashes])):
                        raise ValueError("首次执行仅接受今天原计划、活动包SHA与独立许可身份；不能设置账户、金额、时钟或股数")
                    grant = dict(body, now=datetime.now(timezone.utc))
                    if broker_route:
                        broker = self.server.cohort.best_broker
                        if broker is None:
                            raise ValueError("尚未配置原策略券商模拟账户")
                        grant["account_id"] = broker.engine._get("best_account", None)
                        result = broker.authorize_first_execution(**grant)
                    else:
                        result = self.server.cohort.authorize_first_execution(**grant)
                elif path in {"/api/applied/catchup-renew", "/api/applied/broker-catchup-renew"}:
                    required = {"execution_date", "deadline_utc", "expected_prior_sha256", "renewal_id", "allowed_codes"}
                    strings = required - {"allowed_codes"}
                    codes = body.get("allowed_codes")
                    optional = {"single_sell_spread_bps"} if path == "/api/applied/catchup-renew" else set()
                    if (set(body) not in (required, required | optional)
                            or ("single_sell_spread_bps" in body and
                                (type(body["single_sell_spread_bps"]) is not int or body["single_sell_spread_bps"] != 60
                                 or codes != ["US.KDK"]))
                            or not all(isinstance(body.get(key), str) for key in strings)
                            or len(body["expected_prior_sha256"]) != 64
                            or any(char not in "0123456789abcdef" for char in body["expected_prior_sha256"])
                            or not 1 <= len(body["renewal_id"]) <= 64 or not body["renewal_id"][0].isalnum()
                            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in body["renewal_id"])
                            or not isinstance(codes, list) or not 1 <= len(codes) <= 40
                            or any(not isinstance(code, str) or not code.startswith("US.") for code in codes)
                            or len(codes) != len(set(codes))):
                        raise ValueError("人工续期仅接受原日期、新截止、旧授权SHA、唯一续期身份及明确剩余证券")
                    clock = datetime.now(timezone.utc)
                    if path == "/api/applied/broker-catchup-renew":
                        broker = self.server.cohort.best_broker
                        if broker is None:
                            raise ValueError("尚未配置原策略券商模拟账户")
                        result = broker.renew_catchup(**body,
                            account_id=broker.engine._get("best_account", None), now=clock)
                    else:
                        result = self.server.cohort.renew_catchup(**body, now=clock)
                elif path in {"/api/applied/catchup", "/api/applied/broker-catchup"}:
                    allowed = {"execution_date", "deadline_utc"}
                    if path == "/api/applied/broker-catchup" and "quote_refresh" in body:
                        allowed.add("quote_refresh")
                    if (set(body) != allowed or not all(isinstance(body.get(key), str) for key in ("execution_date", "deadline_utc"))
                            or ("quote_refresh" in body and type(body["quote_refresh"]) is not bool)):
                        raise ValueError("当日补执行仅接受原日期/截止及券商明确布尔 quote_refresh")
                    if path == "/api/applied/broker-catchup":
                        broker = self.server.cohort.best_broker
                        if broker is None:
                            raise ValueError("尚未配置策略券商模拟账户")
                        options = {"quote_refresh": body["quote_refresh"]} if "quote_refresh" in body else {}
                        result = broker.authorize_catchup(
                            execution_date=body["execution_date"], deadline_utc=body["deadline_utc"],
                            account_id=broker.engine._get("best_account", None),
                            include_deferred_sells=True, now=datetime.now(timezone.utc), **options)
                    else:
                        result = self.server.cohort.authorize_catchup(
                            execution_date=body["execution_date"], deadline_utc=body["deadline_utc"],
                            now=datetime.now(timezone.utc))
                elif body:
                    raise ValueError("策略控制接口不接受账户、金额或额外参数")
                elif path == "/api/applied/mark":
                    result = self.server.cohort.mark_current_books()
                elif path in {"/api/applied/reconcile", "/api/applied/broker-start"}:
                    broker = self.server.cohort.best_broker
                    if broker is None:
                        raise ValueError("尚未配置策略券商模拟账户")
                    result = broker.reconcile() if path == "/api/applied/reconcile" else broker.start()
                else:
                    actions = {"/api/applied/start": self.server.cohort.start,
                               "/api/applied/stop": lambda: self.server.cohort.stop(scalar=True),
                               "/api/applied/halt": self.server.cohort.halt}
                    if path not in actions:
                        return self._reply(404, {"ok": False, "error": "接口不存在"})
                    result = actions[path]()
            elif path == "/api/live/connect":
                result = self.server.live.connect(**body)
            elif path == "/api/live/select":
                result = self.server.live.select(**body)
            elif path == "/api/live/refresh":
                if body:
                    raise ValueError("刷新只读账户不接受额外参数")
                result = self.server.live.refresh()
            elif path == "/api/import":
                result = engine.import_strategy(body["manifest"])
            elif path == "/api/switch":
                result = engine.switch(body["strategy_id"])
            elif path == "/api/preview":
                result = engine.preview()
            elif path == "/api/step":
                result = engine.step()
            elif path == "/api/start":
                result = engine.start()
            elif path == "/api/stop":
                result = engine.stop()
            elif path == "/api/halt":
                result = engine.halt()
            elif path == "/api/reset-halt":
                result = engine.reset_halt()
            elif path == "/api/demo":
                result = engine.demo()
            elif path == "/api/connect":
                result = engine.connect(**body)
            elif path == "/api/mode":
                result = engine.set_mode(**body)
            elif path == "/api/limits":
                result = engine.set_limits(body)
            elif path == "/api/reconcile":
                result = engine.reconcile()
            elif path == "/api/inspect-daily":
                from .imports import inspect_daily
                result = inspect_daily(body["payload"])
            else:
                return self._reply(404, {"ok": False, "error": "接口不存在"})
            self._reply(200, {"ok": True, "data": result})
        except Exception as exc:
            self._reply(400, {"ok": False, "error": str(exc)[:2000]})


def main():
    parser = argparse.ArgumentParser(description="Moomoo 安全模拟交易组件（不支持实盘）")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="每日状态根下的组件目录；省略使用项目共享存储配置")
    parser.add_argument("--applied-strategies", action="store_true", help="接入三个固定策略的独立纸面账本")
    parser.add_argument("--repo-root", type=Path, default=Path("D:/us-tech-quant"))
    parser.add_argument("--manual-data-updates", action="store_true", help="仅由明确每日更新准备目标及图表；日常调度消费冻结缓存")
    parser.add_argument("--activate-applied", action="store_true", help="启动已授权的策略纸面调度")
    parser.add_argument("--moomoo-best", action="store_true", help="为当前已绑定策略接入原美股模拟账户，预算10000美元")
    parser.add_argument("--execution-delay-minutes", type=int, default=None,
                        help="开盘后延迟执行分钟数；策略默认25分钟（纽约09:55），仅影响未执行的新信号")
    parser.add_argument("--execution-window-seconds", type=int, default=None,
                        help="纸面窗口（旧1至600秒，或25分钟延迟配1500秒）；策略默认1500秒，仅影响未执行的新信号")
    parser.add_argument("--broker-execution-window-seconds", type=int, default=None,
                        help="MOOMOO simulation only, 1-3600 seconds; defaults to the paper window (1500 seconds); new signals only")
    parser.add_argument("--qualified-quotes-only", action=argparse.BooleanOptionalAction, default=None,
                        help="逐股执行合格报价，未成交资金保留现金；省略沿用持久配置")
    args = parser.parse_args()
    if args.manual_data_updates and not args.applied_strategies:
        parser.error("--manual-data-updates requires --applied-strategies")
    if args.activate_applied and not args.applied_strategies:
        parser.error("--activate-applied 需要 --applied-strategies")
    if args.moomoo_best and not args.applied_strategies:
        parser.error("--moomoo-best 需要 --applied-strategies")
    if args.execution_delay_minutes is not None and (not args.applied_strategies or
            not 0 <= args.execution_delay_minutes <= 180):
        parser.error("--execution-delay-minutes 需要策略模式，且为0至180分钟")
    if args.execution_window_seconds is not None and (not args.applied_strategies or
            not (1 <= args.execution_window_seconds <= 600 or
                (args.execution_window_seconds == 1500 and args.execution_delay_minutes in (None, 25)))):
        parser.error("--execution-window-seconds 需要策略模式；旧1至600秒，或25分钟延迟配1500秒")
    if args.broker_execution_window_seconds is not None and (not args.moomoo_best or
            not 1 <= args.broker_execution_window_seconds <= 3600):
        parser.error("--broker-execution-window-seconds requires --moomoo-best and 1-3600 seconds")
    if args.qualified_quotes_only is not None and not args.applied_strategies:
        parser.error("--qualified-quotes-only 需要 --applied-strategies")
    if args.applied_strategies:
        # The user default is New York 09:55-10:20 for new ordinary signals.
        # Explicit overrides and the engines' existing-order expiry guards remain authoritative.
        if args.execution_delay_minutes is None:
            args.execution_delay_minutes = 25
        if args.execution_window_seconds is None:
            args.execution_window_seconds = 1500 if args.execution_delay_minutes == 25 else 600
    from scripts.common.storage_paths import resolve
    storage = resolve(args.repo_root)
    default_dir = storage.daily_root / "moomoo_trading_component" / ("applied" if args.applied_strategies else "manual")
    args.data_dir = (args.data_dir or default_dir).expanduser().resolve()
    if args.data_dir == storage.daily_root or not args.data_dir.is_relative_to(storage.daily_root):
        parser.error("交易组件状态必须位于共享 daily_root 下的独立目录")
    engine = Engine(args.data_dir / "manual" if args.applied_strategies else args.data_dir)
    cohort = None
    if args.applied_strategies:
        from .applied_source import DailySource
        from .cohort import Cohort
        from .quotes import MoomooQuoteFeed
        source = DailySource(repo_root=args.repo_root, runtime_root=args.data_dir / "source" / "local")
        cohort = Cohort(args.data_dir / "books", source, MoomooQuoteFeed(),
                        execution_delay_minutes=args.execution_delay_minutes,
                        execution_window_seconds=args.execution_window_seconds,
                        allow_partial_quotes=args.qualified_quotes_only, manual_data_updates=args.manual_data_updates)
        if args.moomoo_best:
            from .best_broker import BestBroker
            broker_source = DailySource(repo_root=args.repo_root, runtime_root=args.data_dir / "source" / "moomoo")
            cohort.best_broker = BestBroker(args.data_dir / "moomoo-best", broker_source,
                                           execution_delay_minutes=args.execution_delay_minutes,
                                           execution_window_seconds=(args.broker_execution_window_seconds
                                               if args.broker_execution_window_seconds is not None
                                               else args.execution_window_seconds),
                                           allow_partial_quotes=args.qualified_quotes_only, manual_data_updates=args.manual_data_updates)
    if cohort is not None:
        cohort._bind_automatic_completion_policy()
    server = LocalServer(args.port, engine, cohort=cohort)
    if args.activate_applied:
        cohort.start()
    print(f"模拟交易控制台 http://127.0.0.1:{server.server_port} · 实盘禁用 · "
          + ("已启动授权模拟调度" if args.activate_applied else "自动执行已停止"), flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.live.close()
        if cohort is not None:
            cohort.close()
        engine.close()


if __name__ == "__main__":
    main()
