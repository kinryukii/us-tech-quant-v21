#!/usr/bin/env python
"""V22.047 R1C: centralized, loopback-only Moomoo OpenD connection profile.

This module is read-only. It validates the local OpenD endpoint, exports a
standard environment map for child processes, and can perform a quote-context
connectivity probe. It never opens a trade context, unlocks trading, or sends
orders.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18441
ENV_HOST_KEYS = (
    "MOOMOO_OPEND_HOST",
    "FUTU_OPEND_HOST",
    "MOOMOO_HOST",
    "FUTU_HOST",
    "OPEND_HOST",
)
ENV_PORT_KEYS = (
    "MOOMOO_OPEND_PORT",
    "FUTU_OPEND_PORT",
    "MOOMOO_PORT",
    "FUTU_PORT",
    "OPEND_PORT",
)


class ProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConnectionProfile:
    schema_version: int
    profile_name: str
    host: str
    port: int
    allow_remote_host: bool
    tcp_timeout_seconds: float
    quote_probe_symbols: tuple[str, ...]
    trade_unlock_required_for_data: bool
    notes: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProfileError(f"PROFILE_NOT_FOUND:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"PROFILE_INVALID_JSON:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ProfileError(f"PROFILE_ROOT_MUST_BE_OBJECT:{path}")
    return payload


def _first_env(keys: tuple[str, ...], environ: Mapping[str, str]) -> str | None:
    for key in keys:
        value = str(environ.get(key, "")).strip()
        if value:
            return value
    return None


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_profile(profile: ConnectionProfile) -> None:
    if profile.schema_version != 1:
        raise ProfileError("UNSUPPORTED_PROFILE_SCHEMA")
    if not profile.host.strip():
        raise ProfileError("OPEND_HOST_EMPTY")
    if not 1 <= int(profile.port) <= 65535:
        raise ProfileError("OPEND_PORT_OUT_OF_RANGE")
    if profile.tcp_timeout_seconds <= 0 or profile.tcp_timeout_seconds > 30:
        raise ProfileError("TCP_TIMEOUT_OUT_OF_RANGE")
    if not profile.allow_remote_host and not is_loopback_host(profile.host):
        raise ProfileError("REMOTE_OPEND_HOST_BLOCKED")
    if profile.trade_unlock_required_for_data:
        raise ProfileError("READ_ONLY_DATA_PROFILE_MUST_NOT_REQUIRE_TRADE_UNLOCK")
    for symbol in profile.quote_probe_symbols:
        if not symbol.startswith("US."):
            raise ProfileError(f"INVALID_QUOTE_PROBE_SYMBOL:{symbol}")


def load_profile(path: Path, environ: Mapping[str, str] | None = None) -> ConnectionProfile:
    payload = read_json(path)
    env = os.environ if environ is None else environ
    host_override = _first_env(ENV_HOST_KEYS, env)
    port_override = _first_env(ENV_PORT_KEYS, env)
    host = host_override or str(payload.get("host", DEFAULT_HOST))
    raw_port: Any = port_override if port_override is not None else payload.get("port", DEFAULT_PORT)
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"OPEND_PORT_INVALID:{raw_port}") from exc
    profile = ConnectionProfile(
        schema_version=int(payload.get("schema_version", 1)),
        profile_name=str(payload.get("profile_name", "LOCAL_MOOMOO_OPEND")),
        host=host,
        port=port,
        allow_remote_host=bool(payload.get("allow_remote_host", False)),
        tcp_timeout_seconds=float(payload.get("tcp_timeout_seconds", 2.0)),
        quote_probe_symbols=tuple(str(x).upper() for x in payload.get("quote_probe_symbols", [])),
        trade_unlock_required_for_data=bool(payload.get("trade_unlock_required_for_data", False)),
        notes=str(payload.get("notes", "")),
    )
    validate_profile(profile)
    return profile


def environment_map(profile: ConnectionProfile) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ENV_HOST_KEYS:
        result[key] = profile.host
    for key in ENV_PORT_KEYS:
        result[key] = str(profile.port)
    return result


def tcp_probe(profile: ConnectionProfile) -> tuple[bool, str]:
    try:
        with socket.create_connection(
            (profile.host, profile.port), timeout=profile.tcp_timeout_seconds
        ):
            return True, "TCP_CONNECTED"
    except OSError as exc:
        return False, f"TCP_CONNECT_FAILED:{type(exc).__name__}:{exc}"


def _rows_from_result(result: Any) -> tuple[bool, int, str]:
    if not isinstance(result, tuple) or len(result) < 2:
        return False, 0, "UNEXPECTED_API_RESULT"
    code, data = result[0], result[1]
    ok = code == 0 or str(code).upper() in {"0", "RET_OK", "OK"}
    if not ok:
        return False, 0, str(data)
    if hasattr(data, "__len__"):
        try:
            return True, int(len(data)), "QUOTE_API_OK"
        except Exception:
            pass
    return True, 0, "QUOTE_API_OK"


def quote_context_probe(profile: ConnectionProfile) -> dict[str, Any]:
    """Open only a quote context. Never opens or unlocks a trade context."""
    try:
        import moomoo  # type: ignore
    except Exception as exc:
        return {
            "quote_probe_ok": False,
            "quote_probe_reason": f"MOOMOO_IMPORT_FAILED:{type(exc).__name__}:{exc}",
            "quote_row_count": 0,
        }

    context = None
    try:
        context = moomoo.OpenQuoteContext(host=profile.host, port=profile.port)
        method = getattr(context, "get_market_snapshot", None)
        if callable(method):
            ok, count, reason = _rows_from_result(method(list(profile.quote_probe_symbols)))
            return {
                "quote_probe_ok": ok,
                "quote_probe_reason": reason,
                "quote_row_count": count,
            }
        method = getattr(context, "get_stock_quote", None)
        if callable(method):
            ok, count, reason = _rows_from_result(method(list(profile.quote_probe_symbols)))
            return {
                "quote_probe_ok": ok,
                "quote_probe_reason": reason,
                "quote_row_count": count,
            }
        return {
            "quote_probe_ok": False,
            "quote_probe_reason": "QUOTE_METHOD_NOT_AVAILABLE",
            "quote_row_count": 0,
        }
    except Exception as exc:
        return {
            "quote_probe_ok": False,
            "quote_probe_reason": f"QUOTE_CONTEXT_FAILED:{type(exc).__name__}:{exc}",
            "quote_row_count": 0,
        }
    finally:
        if context is not None:
            close = getattr(context, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


def build_summary(profile: ConnectionProfile, do_quote_probe: bool) -> dict[str, Any]:
    tcp_ok, tcp_reason = tcp_probe(profile)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_at_utc": utc_now_iso(),
        "profile": asdict(profile),
        "loopback_only": not profile.allow_remote_host,
        "tcp_probe_ok": tcp_ok,
        "tcp_probe_reason": tcp_reason,
        "quote_probe_attempted": bool(do_quote_probe and tcp_ok),
        "trade_context_opened": False,
        "trade_unlock_called": False,
        "order_submission_called": False,
        "environment_map": environment_map(profile),
    }
    if do_quote_probe and tcp_ok:
        summary.update(quote_context_probe(profile))
    else:
        summary.update(
            {
                "quote_probe_ok": False,
                "quote_probe_reason": "NOT_ATTEMPTED" if not do_quote_probe else "TCP_UNAVAILABLE",
                "quote_row_count": 0,
            }
        )
    summary["final_status"] = (
        "PASS_V22_047_R1C_MOOMOO_OPEND_PROFILE_READY"
        if tcp_ok and (not do_quote_probe or summary["quote_probe_ok"])
        else "WARN_V22_047_R1C_MOOMOO_OPEND_PROFILE_NOT_READY"
    )
    return summary


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output")
    parser.add_argument("--quote-probe", action="store_true")
    parser.add_argument("--require-tcp", action="store_true")
    parser.add_argument("--print-env-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        profile = load_profile(Path(args.profile))
        if args.print_env_json:
            print(json.dumps(environment_map(profile), sort_keys=True))
            return 0
        summary = build_summary(profile, bool(args.quote_probe))
        if args.output:
            write_json(Path(args.output), summary)
        for key in [
            "final_status",
            "tcp_probe_ok",
            "tcp_probe_reason",
            "quote_probe_attempted",
            "quote_probe_ok",
            "quote_probe_reason",
        ]:
            print(f"{key}={summary.get(key)}")
        print(f"opend_host={profile.host}")
        print(f"opend_port={profile.port}")
        if args.require_tcp and not summary["tcp_probe_ok"]:
            return 2
        if args.quote_probe and not summary["quote_probe_ok"]:
            return 3
        return 0
    except ProfileError as exc:
        print(f"final_status=FAIL_V22_047_R1C_PROFILE_INVALID", file=sys.stderr)
        print(f"error={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
