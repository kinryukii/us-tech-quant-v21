"""Loopback-only dashboard. JSON + per-process CSRF token protect mutations."""
from __future__ import annotations

import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from .core import Engine

FRAME_ORIGINS = tuple(f"http://{host}:{port}" for host in ("127.0.0.1", "localhost")
                      for port in (8501, 8506, 8507, 8516))
LIVE_READ_ENDPOINTS = frozenset({"/api/live/connect", "/api/live/select", "/api/live/refresh"})


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, engine, live=None, cohort=None):
        self.engine = engine
        self.cohort = cohort
        self.token = secrets.token_urlsafe(32)
        self.live_token = secrets.token_urlsafe(32)
        if live is None:
            from .live import LiveReadOnly
            live = LiveReadOnly()
        self.live = live
        super().__init__(("127.0.0.1", port), Handler)


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
                "live_execution_enabled": False, "pages": ["paper", "live"]}})
        if path == "/api/token":
            return self._reply(200, {"ok": True, "data": {"token": self.server.token}})
        if path == "/api/live/token":
            return self._reply(200, {"ok": True, "data": {"token": self.server.live_token}})
        if path == "/api/live/state":
            return self._reply(200, {"ok": True, "data": self.server.live.state()})
        if path == "/api/state":
            return self._reply(200, {"ok": True, "data": self.server.engine.state()})
        if path == "/api/applied/state":
            if self.server.cohort is None:
                return self._reply(503, {"ok": False, "error": "三策略纸面账户尚未配置"})
            return self._reply(200, {"ok": True, "data": self.server.cohort.state()})
        if path == "/api/applied/trades.csv":
            if self.server.cohort is None:
                return self._reply(503, {"ok": False, "error": "三策略纸面账户尚未配置"})
            fields = ["strategy_id", "account_id", "signal_date", "execution_date", "filled_at",
                      "code", "side", "qty", "fill_price", "fee", "status", "quote_asof", "source", "id"]
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.server.cohort.trades())
            return self._reply(200, ("\ufeff" + stream.getvalue()).encode("utf-8"), "text/csv; charset=utf-8")
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
                    raise ValueError("三策略纸面账户尚未配置")
                if body:
                    raise ValueError("三策略控制接口不接受账户、金额或额外参数")
                if path == "/api/applied/reconcile":
                    broker = self.server.cohort.best_broker
                    if broker is None:
                        raise ValueError("尚未配置策略券商模拟账户")
                    result = broker.reconcile()
                else:
                    actions = {"/api/applied/start": self.server.cohort.start,
                               "/api/applied/stop": self.server.cohort.stop,
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
    parser.add_argument("--activate-applied", action="store_true", help="启动已授权的三策略纸面调度")
    parser.add_argument("--moomoo-best", action="store_true", help="为 HGB 对角风险接入唯一美股模拟账户，预算10000美元")
    parser.add_argument("--execution-delay-minutes", type=int, default=None,
                        help="开盘后延迟执行分钟数；省略沿用持久配置")
    parser.add_argument("--execution-window-seconds", type=int, default=None,
                        help="计划执行窗口（1至600秒）；省略沿用持久配置")
    parser.add_argument("--broker-execution-window-seconds", type=int, default=None,
                        help="MOOMOO simulation only, 1-3600 seconds; new signals only")
    parser.add_argument("--qualified-quotes-only", action=argparse.BooleanOptionalAction, default=None,
                        help="逐股执行合格报价，未成交资金保留现金；省略沿用持久配置")
    args = parser.parse_args()
    if args.activate_applied and not args.applied_strategies:
        parser.error("--activate-applied 需要 --applied-strategies")
    if args.moomoo_best and not args.applied_strategies:
        parser.error("--moomoo-best 需要 --applied-strategies")
    if args.execution_delay_minutes is not None and (not args.applied_strategies or
            not 0 <= args.execution_delay_minutes <= 180):
        parser.error("--execution-delay-minutes 需要三策略模式，且为0至180分钟")
    if args.execution_window_seconds is not None and (not args.applied_strategies or
            not 1 <= args.execution_window_seconds <= 600):
        parser.error("--execution-window-seconds 需要三策略模式，且为1至600秒")
    if args.broker_execution_window_seconds is not None and (not args.moomoo_best or
            not 1 <= args.broker_execution_window_seconds <= 3600):
        parser.error("--broker-execution-window-seconds requires --moomoo-best and 1-3600 seconds")
    if args.qualified_quotes_only is not None and not args.applied_strategies:
        parser.error("--qualified-quotes-only 需要 --applied-strategies")
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
                        allow_partial_quotes=args.qualified_quotes_only)
        if args.moomoo_best:
            from .best_broker import BestBroker
            broker_source = DailySource(repo_root=args.repo_root, runtime_root=args.data_dir / "source" / "moomoo")
            cohort.best_broker = BestBroker(args.data_dir / "moomoo-best", broker_source,
                                           execution_delay_minutes=args.execution_delay_minutes,
                                           execution_window_seconds=(args.broker_execution_window_seconds
                                               if args.broker_execution_window_seconds is not None
                                               else args.execution_window_seconds),
                                           allow_partial_quotes=args.qualified_quotes_only)
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
