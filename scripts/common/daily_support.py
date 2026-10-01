"""Shared file, lock, and quote quota helpers for retained research readers.

Provider snapshots stay separate. Incomplete inputs never become today's Top20.
This is a presentation/acquisition adapter, not a replacement strategy runner.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo


def emit(message):
    print(json.dumps({'event': 'progress', 'message': message}, ensure_ascii=False), flush=True)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def single_update(root):
    """OS-owned lock: released after crashes, shared by UI and command line."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'update.lock').open('a+b') as handle:
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('已有更新任务运行中，请等待该任务完成。') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def live_quota(paths, work):
    from scripts.storage.refresh_market_data import load_module, PROFILE
    profile_module = load_module(paths.repo_root / PROFILE, 'today_quote_profile')
    profile = profile_module.load_profile(paths.repo_root / 'config/moomoo_opend_connection.json', dict(os.environ))
    connected, reason = profile_module.tcp_probe(profile)
    if not connected:
        raise ConnectionError('Moomoo OpenD 未连接：' + str(reason))
    appdata = work / 'sdk_appdata'
    appdata.mkdir(parents=True, exist_ok=True)
    os.environ['APPDATA'] = str(appdata)
    sdk = importlib.import_module('moomoo')
    sdk.SysConfig.set_all_thread_daemon(True)
    context = sdk.OpenQuoteContext(host=profile.host, port=profile.port, is_async_connect=True)
    try:
        context.set_sync_query_connect_timeout(10)
        code, quota = context.get_history_kl_quota(get_detail=True)
        if code != sdk.RET_OK:
            raise RuntimeError('MOOMOO_QUOTA_QUERY_FAILED')
        return quota
    finally:
        context.close()


