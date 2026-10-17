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


def _wincheck(success, operation):
    if not success:
        import ctypes
        raise OSError(operation + ':' + str(ctypes.WinError(ctypes.get_last_error())))


def _check_provider_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError('PROVIDER_CANCELLED')


def _windows_provider(argv, cwd, stream, timeout, *, input_stream=None, cancel_event=None):
    """Create directly in a non-inherited kill-on-close job, before any code runs.

    JOB_LIST closes even the create-suspended/assign-job parent-death gap.
    No breakaway flags or PID-based ownership checks are used.
    """
    import ctypes as c
    from ctypes import wintypes as w
    import msvcrt
    import _winapi

    class BasicLimits(c.Structure):
        _fields_ = [('ProcessTime', c.c_int64), ('JobTime', c.c_int64), ('Flags', w.DWORD),
                    ('MinWorkingSet', c.c_size_t), ('MaxWorkingSet', c.c_size_t),
                    ('ActiveProcesses', w.DWORD), ('Affinity', c.c_size_t),
                    ('Priority', w.DWORD), ('Scheduling', w.DWORD)]
    class ExtendedLimits(c.Structure):
        _fields_ = [('Basic', BasicLimits), ('IoCounters', c.c_uint64 * 6),
                    ('ProcessMemory', c.c_size_t), ('JobMemory', c.c_size_t),
                    ('PeakProcessMemory', c.c_size_t), ('PeakJobMemory', c.c_size_t)]
    class Startup(c.Structure):
        _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                    ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD),
                    ('xchars', w.DWORD), ('ychars', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                    ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', c.c_void_p),
                    ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]
    class StartupEx(c.Structure):
        _fields_ = [('info', Startup), ('attributes', c.c_void_p)]
    class ProcessInfo(c.Structure):
        _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]

    _check_provider_cancel(cancel_event)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    def api(name, result, args):
        function = getattr(kernel, name); function.restype = result; function.argtypes = args
        return function
    create_job = api('CreateJobObjectW', w.HANDLE, [c.c_void_p, w.LPCWSTR])
    set_job = api('SetInformationJobObject', w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD])
    initialize = api('InitializeProcThreadAttributeList', w.BOOL, [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)])
    update = api('UpdateProcThreadAttribute', w.BOOL,
                 [c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p])
    delete = api('DeleteProcThreadAttributeList', None, [c.c_void_p])
    create = api('CreateProcessW', w.BOOL, [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL,
                  w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(StartupEx), c.POINTER(ProcessInfo)])
    in_job = api('IsProcessInJob', w.BOOL, [w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)])
    resume = api('ResumeThread', w.DWORD, [w.HANDLE])
    close = api('CloseHandle', w.BOOL, [w.HANDLE])
    job, attributes, handles, process = None, None, [], ProcessInfo()
    try:
        job = create_job(None, None); _wincheck(job, 'CREATE_JOB')
        limits = ExtendedLimits(); limits.Basic.Flags = 0x2000  # KILL_ON_JOB_CLOSE, no breakaway.
        _wincheck(set_job(job, 9, c.byref(limits), c.sizeof(limits)), 'SET_KILL_ON_JOB_CLOSE')
        size = c.c_size_t()
        initialize(None, 2, 0, c.byref(size))
        if not size.value:
            _wincheck(False, 'ATTRIBUTE_LIST_SIZE')
        buffer = c.create_string_buffer(size.value)
        _wincheck(initialize(buffer, 2, 0, c.byref(size)), 'INITIALIZE_ATTRIBUTES')
        attributes = buffer
        job_list = (w.HANDLE * 1)(job)
        _wincheck(update(attributes, 0, 0x2000D, job_list, c.sizeof(job_list), None, None), 'ATOMIC_JOB_LIST')
        current = _winapi.GetCurrentProcess()
        from contextlib import nullcontext
        with (nullcontext(input_stream) if input_stream is not None else open(os.devnull, 'rb')) as empty:
            for value in (msvcrt.get_osfhandle(empty.fileno()), msvcrt.get_osfhandle(stream.fileno())):
                handles.append(_winapi.DuplicateHandle(current, value, current, 0, True, _winapi.DUPLICATE_SAME_ACCESS))
            inherited = (w.HANDLE * len(handles))(*handles)
            _wincheck(update(attributes, 0, 0x20002, inherited, c.sizeof(inherited), None, None), 'ONLY_LOG_HANDLES')
            startup = StartupEx(); startup.info.cb = c.sizeof(startup)
            startup.info.flags = subprocess.STARTF_USESTDHANDLES
            startup.info.stdin, startup.info.stdout, startup.info.stderr = handles[0], handles[1], handles[1]
            startup.attributes = c.cast(attributes, c.c_void_p)
            # Born inside the job and suspended. Even a crash before ResumeThread kills it.
            flags = 0x80000 | subprocess.CREATE_NO_WINDOW | 0x4
            command = c.create_unicode_buffer(subprocess.list2cmdline(argv))
            _check_provider_cancel(cancel_event)
            _wincheck(create(argv[0], command, None, None, True, flags, None, str(cwd),
                             c.byref(startup), c.byref(process)), 'CREATE_CONTAINED_SUSPENDED')
        contained = w.BOOL()
        _wincheck(in_job(process.process, job, c.byref(contained)) and contained.value, 'CONTAINMENT_VERIFIED')
        _check_provider_cancel(cancel_event)
        _wincheck(True, 'BEFORE_RESUME')
        _wincheck(resume(process.thread) != 0xffffffff, 'RESUME_CONTAINED')
        _winapi.CloseHandle(process.thread); process.thread = None
        kwargs = {'cancel_event': cancel_event} if cancel_event is not None else {}
        return _windows_wait(process.process, argv, timeout, **kwargs)
    finally:
        # Only the parent owns the job handle. Last close kills the entire owned tree,
        # including descendants left behind after a nominally successful module exit.
        try:
            if job:
                _wincheck(close(job), 'CLOSE_OWNED_JOB')
                if process.process:
                    _wincheck(_winapi.WaitForSingleObject(process.process, 10000) == _winapi.WAIT_OBJECT_0,
                              'OWNED_PROCESS_TERMINATION')
        finally:
            if process.thread: _winapi.CloseHandle(process.thread)
            if process.process: _winapi.CloseHandle(process.process)
            for handle in handles: _winapi.CloseHandle(handle)
            if attributes is not None: delete(attributes)


def _windows_wait(handle, argv, timeout, *, cancel_event=None):
    # Short finite waits also let Python cancellation reach the cleanup finally.
    import _winapi
    import math
    import time
    deadline = time.monotonic() + timeout
    while True:
        _check_provider_cancel(cancel_event)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout)
        wait = _winapi.WaitForSingleObject(handle, min(250, math.ceil(remaining * 1000)))
        if wait == _winapi.WAIT_OBJECT_0:
            return _winapi.GetExitCodeProcess(handle)
        if wait != _winapi.WAIT_TIMEOUT:
            raise OSError('PROVIDER_WAIT_FAILED:' + str(wait))


def _posix_provider(argv, cwd, stream, timeout, *, input_stream=None, cancel_event=None):
    """Compatibility path: own a process group; clean it on return/interruption.

    Abrupt parent-death containment is a Windows job guarantee, not a POSIX claim.
    """
    import signal
    import time
    _check_provider_cancel(cancel_event)
    process = subprocess.Popen(argv, cwd=cwd, stdin=input_stream if input_stream is not None else subprocess.DEVNULL, stdout=stream,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        if cancel_event is None:
            return process.wait(timeout=timeout)
        deadline = time.monotonic() + timeout
        while True:
            _check_provider_cancel(cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                return process.wait(timeout=min(.25, remaining))
            except subprocess.TimeoutExpired:
                pass
    finally:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait(timeout=10)


MAX_PROVIDER_INPUT_BYTES = 1024 * 1024


def run_provider(paths, module, arguments, log, *, timeout=3600, input_path=None, cancel_event=None):
    """Run literal module argv in an owned finite-lifetime process tree.

    Storage/source/network authority remains with the caller and original module.
    Log setup and containment failures stop before module execution; no fallback
    starts an uncontained Windows child. Cancellation cleans up and propagates.
    Optional local UTF-8 stdin is snapshotted within a strict 1 MiB bound before
    launch; its temporary file stays beside the caller-owned request and closes
    with this run. The original no-input call keeps its NUL stdin and argv.
    An optional event requests owned-tree cleanup; completion is reported only
    after cleanup. The original child environment inheritance is unchanged.
    """
    import math
    import re
    result = {'module': module, 'exit_code': -1, 'log_path': str(log),
              'lifecycle': 'WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE' if os.name == 'nt' else 'POSIX_OWNED_PROCESS_GROUP'}
    try:
        _check_provider_cancel(cancel_event)
        timeout = float(timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError('PROVIDER_TIMEOUT_INVALID')
        if not isinstance(module, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module):
            raise ValueError('PROVIDER_MODULE_INVALID')
        argv = [str(paths.python_exe), '-X', 'utf8', '-B', '-m', module, *map(str, arguments)]
        if any('\0' in argument for argument in argv):
            raise ValueError('PROVIDER_ARGUMENT_NULL')
        from contextlib import ExitStack
        with ExitStack() as owned:
            input_stream = None
            if input_path is not None:
                import stat
                import tempfile
                request = Path(input_path)
                if (not request.is_absolute() or str(request).startswith('\\\\')
                        or request.is_symlink() or request.resolve() != request.absolute()):
                    raise ValueError('PROVIDER_INPUT_NOT_LOCAL_REGULAR')
                with request.open('rb') as original:
                    info = os.fstat(original.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('PROVIDER_INPUT_NOT_LOCAL_REGULAR')
                    if info.st_size > MAX_PROVIDER_INPUT_BYTES:
                        raise ValueError('PROVIDER_INPUT_TOO_LARGE')
                    payload = original.read(MAX_PROVIDER_INPUT_BYTES + 1)
                if len(payload) > MAX_PROVIDER_INPUT_BYTES:
                    raise ValueError('PROVIDER_INPUT_TOO_LARGE')
                payload.decode('utf-8')
                input_stream = owned.enter_context(tempfile.TemporaryFile(mode='w+b', dir=request.parent))
                input_stream.write(payload); input_stream.flush(); input_stream.seek(0)
            log = Path(log); log.parent.mkdir(parents=True, exist_ok=True)
            stream = owned.enter_context(log.open('w', encoding='utf-8'))
            runner = _windows_provider if os.name == 'nt' else _posix_provider
            kwargs = {'input_stream': input_stream} if input_stream is not None else {}
            if cancel_event is not None:
                kwargs['cancel_event'] = cancel_event
            result['exit_code'] = runner(argv, paths.repo_root, stream, timeout, **kwargs)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result['exit_code'] = -1
        result['error'] = type(exc).__name__ + ':' + str(exc)
    return result


def open_quote_context(sdk, *, host, port, creation_timeout=10.0):
    """Create only our asynchronous quote context on an owned daemon thread.

    The SDK reconnect Timer inherits its creator's daemon flag rather than
    reading SysConfig. Import the SDK on the caller before entering this helper.
    Timed-out construction closes a context if it later becomes available.
    """
    import threading
    creation_timeout = float(creation_timeout)
    if not 0 < creation_timeout < float("inf"):
        raise ValueError("QUOTE_CONTEXT_CREATION_TIMEOUT_INVALID")
    completed, abandoned = threading.Event(), threading.Event()
    guard, state = threading.Lock(), {}

    def create():
        try:
            context = sdk.OpenQuoteContext(host=host, port=port, is_async_connect=True)
            with guard:
                late = abandoned.is_set()
                if not late:
                    state["context"] = context
            if late:
                context.close()
        except Exception as exc:
            with guard:
                state["error"] = exc
        finally:
            completed.set()

    worker = threading.Thread(target=create, name="daily-quote-context-constructor", daemon=True)
    worker.start()
    ready = completed.wait(creation_timeout)
    with guard:
        if not ready:
            abandoned.set()
        context = state.pop("context", None)
        error = state.get("error")
    if not ready:
        if context is not None:
            context.close()
        raise TimeoutError("QUOTE_CONTEXT_CREATION_TIMEOUT")
    if error is not None:
        raise error
    if context is None:
        raise RuntimeError("QUOTE_CONTEXT_CREATION_NO_RESULT")
    return context


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
    context = open_quote_context(sdk, host=profile.host, port=profile.port)
    try:
        context.set_sync_query_connect_timeout(10)
        code, quota = context.get_history_kl_quota(get_detail=True)
        if code != sdk.RET_OK:
            raise RuntimeError('MOOMOO_QUOTA_QUERY_FAILED')
        return quota
    finally:
        context.close()


