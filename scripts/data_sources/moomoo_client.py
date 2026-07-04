"""Research-only Moomoo OpenD quote client wrapper.

This module deliberately exposes quote/data functions only. It never imports or
calls Moomoo trade contexts, unlock APIs, or broker actions.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any


class MoomooClientError(RuntimeError):
    """Base error for Moomoo quote-client failures."""


class MoomooApiMissingError(MoomooClientError):
    """Raised when moomoo-api is not installed in the active Python runtime."""


class MoomooOpenDUnavailableError(MoomooClientError):
    """Raised when OpenD cannot be reached or quote calls fail."""


@dataclass(frozen=True)
class MoomooConnectionConfig:
    host: str
    port: int


def env_config() -> MoomooConnectionConfig:
    host = os.environ.get("MOOMOO_OPEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    raw_port = os.environ.get("MOOMOO_OPEND_PORT", "11111").strip() or "11111"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise MoomooClientError(f"Invalid MOOMOO_OPEND_PORT={raw_port!r}") from exc
    return MoomooConnectionConfig(host=host, port=port)


def import_moomoo() -> Any:
    try:
        return importlib.import_module("moomoo")
    except ImportError as exc:
        raise MoomooApiMissingError(
            "moomoo-api is not installed in this Python environment. "
            "Install the official moomoo-api package and start OpenD; no yfinance fallback is used."
        ) from exc


def _ret_ok(module: Any, ret: Any) -> bool:
    ok = getattr(module, "RET_OK", 0)
    return ret == ok or str(ret).upper() in {"0", "RET_OK", "OK"}


class MoomooQuoteClient:
    """Close-safe wrapper around moomoo.OpenQuoteContext."""

    research_only = True
    official_adoption_allowed = False
    broker_action_allowed = False

    def __init__(self, host: str | None = None, port: int | None = None, quote_ctx: Any | None = None, module: Any | None = None):
        config = env_config()
        self.host = host or config.host
        self.port = int(port if port is not None else config.port)
        self._module = module
        self._ctx = quote_ctx
        self._owns_context = quote_ctx is None

    @property
    def module(self) -> Any:
        if self._module is None:
            self._module = import_moomoo()
        return self._module

    @property
    def ctx(self) -> Any:
        if self._ctx is None:
            module = self.module
            try:
                self._ctx = module.OpenQuoteContext(host=self.host, port=self.port)
            except Exception as exc:
                raise MoomooOpenDUnavailableError(f"Moomoo OpenD quote context unavailable at {self.host}:{self.port}: {exc}") from exc
        return self._ctx

    def __enter__(self) -> "MoomooQuoteClient":
        _ = self.ctx
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._ctx is not None and self._owns_context:
            close = getattr(self._ctx, "close", None)
            if callable(close):
                close()
        self._ctx = None

    def checked_call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self.ctx, method_name)
        try:
            result = method(*args, **kwargs)
        except Exception as exc:
            raise MoomooOpenDUnavailableError(f"Moomoo quote call {method_name} failed: {exc}") from exc
        if isinstance(result, tuple) and len(result) >= 2:
            ret, payload = result[0], result[1]
            if not _ret_ok(self.module, ret):
                raise MoomooOpenDUnavailableError(f"Moomoo quote call {method_name} returned {ret}: {payload}")
            return payload if len(result) == 2 else result[1:]
        return result

    def health_check(self) -> dict[str, Any]:
        payload = {
            "host": self.host,
            "port": self.port,
            "moomoo_api_imported": False,
            "opend_reachable": False,
            "quote_context_created": False,
            "minimal_quote_function_ok": False,
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "error": "",
        }
        try:
            _ = self.module
            payload["moomoo_api_imported"] = True
            _ = self.ctx
            payload["quote_context_created"] = True
            self.checked_call("get_market_state", ["US.AAPL"])
            payload["opend_reachable"] = True
            payload["minimal_quote_function_ok"] = True
        except MoomooClientError as exc:
            payload["error"] = str(exc)
        except Exception as exc:
            payload["error"] = f"Unexpected Moomoo health-check failure: {exc}"
        payload["final_status"] = "PASS" if payload["minimal_quote_function_ok"] else "FAIL"
        return payload
