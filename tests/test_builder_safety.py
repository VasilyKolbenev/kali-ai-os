"""Tests for kernel.builder.safety_gate — security critical, 8+ tests required."""

from __future__ import annotations

import pytest

from kernel.builder.safety_gate import SafetyResult, check_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe(code: str) -> SafetyResult:
    result = check_code(code)
    return result


# ---------------------------------------------------------------------------
# Safe code — must pass
# ---------------------------------------------------------------------------


def test_empty_code_is_safe() -> None:
    result = check_code("")
    assert result.safe is True
    assert result.issues == []


def test_simple_function_is_safe() -> None:
    code = """
def greet(name: str) -> str:
    return f"Hello, {name}"
"""
    result = check_code(code)
    assert result.safe is True
    assert result.issues == []


def test_normal_imports_allowed() -> None:
    """json, logging, datetime must not be blocked."""
    code = """
import json
import logging
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
"""
    result = check_code(code)
    assert result.safe is True
    assert result.issues == []


def test_standard_class_is_safe() -> None:
    code = """
class MyAgent:
    def __init__(self) -> None:
        self._data: list[int] = []

    def add(self, value: int) -> None:
        self._data.append(value)
"""
    result = check_code(code)
    assert result.safe is True


# ---------------------------------------------------------------------------
# Blocked imports
# ---------------------------------------------------------------------------


def test_import_subprocess_blocked() -> None:
    code = "import subprocess"
    result = check_code(code)
    assert result.safe is False
    assert any("subprocess" in issue for issue in result.issues)


def test_import_from_subprocess_blocked() -> None:
    code = "from subprocess import run, PIPE"
    result = check_code(code)
    assert result.safe is False
    assert any("subprocess" in issue for issue in result.issues)


def test_import_importlib_blocked() -> None:
    code = "import importlib"
    result = check_code(code)
    assert result.safe is False


def test_import_ctypes_blocked() -> None:
    code = "import ctypes"
    result = check_code(code)
    assert result.safe is False


def test_import_shutil_blocked() -> None:
    code = "import shutil"
    result = check_code(code)
    assert result.safe is False


def test_import_socket_blocked() -> None:
    code = "import socket"
    result = check_code(code)
    assert result.safe is False


def test_import_threading_blocked() -> None:
    code = "import threading"
    result = check_code(code)
    assert result.safe is False


def test_import_multiprocessing_blocked() -> None:
    code = "import multiprocessing"
    result = check_code(code)
    assert result.safe is False


def test_import_signal_blocked() -> None:
    code = "import signal"
    result = check_code(code)
    assert result.safe is False


# ---------------------------------------------------------------------------
# Blocked builtins
# ---------------------------------------------------------------------------


def test_eval_call_blocked() -> None:
    code = "result = eval('1 + 1')"
    result = check_code(code)
    assert result.safe is False
    assert any("eval" in issue for issue in result.issues)


def test_exec_call_blocked() -> None:
    code = "exec('print(42)')"
    result = check_code(code)
    assert result.safe is False
    assert any("exec" in issue for issue in result.issues)


def test_compile_call_blocked() -> None:
    code = "code_obj = compile('1+1', '<string>', 'eval')"
    result = check_code(code)
    assert result.safe is False
    assert any("compile" in issue for issue in result.issues)


def test_dunder_import_blocked() -> None:
    code = "mod = __import__('os')"
    result = check_code(code)
    assert result.safe is False
    assert any("__import__" in issue for issue in result.issues)


def test_getattr_call_blocked() -> None:
    code = "val = getattr(obj, 'dangerous')"
    result = check_code(code)
    assert result.safe is False
    assert any("getattr" in issue for issue in result.issues)


def test_setattr_call_blocked() -> None:
    code = "setattr(obj, 'x', 42)"
    result = check_code(code)
    assert result.safe is False
    assert any("setattr" in issue for issue in result.issues)


def test_delattr_call_blocked() -> None:
    code = "delattr(obj, 'x')"
    result = check_code(code)
    assert result.safe is False


def test_globals_call_blocked() -> None:
    code = "g = globals()"
    result = check_code(code)
    assert result.safe is False


def test_locals_call_blocked() -> None:
    code = "l = locals()"
    result = check_code(code)
    assert result.safe is False


def test_breakpoint_call_blocked() -> None:
    code = "breakpoint()"
    result = check_code(code)
    assert result.safe is False


# ---------------------------------------------------------------------------
# Blocked attribute chains
# ---------------------------------------------------------------------------


def test_os_system_blocked() -> None:
    code = "import os\nos.system('ls')"
    result = check_code(code)
    # os import is fine; os.system() call is blocked
    assert result.safe is False
    assert any("os.system" in issue for issue in result.issues)


def test_os_popen_blocked() -> None:
    code = "import os\nos.popen('cat /etc/passwd')"
    result = check_code(code)
    assert result.safe is False
    assert any("os.popen" in issue for issue in result.issues)


def test_os_remove_blocked() -> None:
    code = "import os\nos.remove('/tmp/important')"
    result = check_code(code)
    assert result.safe is False
    assert any("os.remove" in issue for issue in result.issues)


def test_os_unlink_blocked() -> None:
    code = "import os\nos.unlink('file.txt')"
    result = check_code(code)
    assert result.safe is False


def test_os_rmdir_blocked() -> None:
    code = "import os\nos.rmdir('/tmp/dir')"
    result = check_code(code)
    assert result.safe is False


def test_os_rename_blocked() -> None:
    code = "import os\nos.rename('a.txt', 'b.txt')"
    result = check_code(code)
    assert result.safe is False


def test_os_makedirs_blocked() -> None:
    code = "import os\nos.makedirs('/tmp/evil', exist_ok=True)"
    result = check_code(code)
    assert result.safe is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_syntax_error_returns_not_safe() -> None:
    code = "def broken(: pass"
    result = check_code(code)
    assert result.safe is False
    assert any("Syntax error" in issue for issue in result.issues)


def test_result_is_safety_result_dataclass() -> None:
    result = check_code("x = 1")
    assert isinstance(result, SafetyResult)
    assert isinstance(result.issues, list)
    assert isinstance(result.warnings, list)


def test_multiple_violations_all_reported() -> None:
    code = "import subprocess\neval('x')\nos.system('rm -rf /')"
    result = check_code(code)
    assert result.safe is False
    # At least two distinct issues
    assert len(result.issues) >= 2


def test_os_path_join_is_allowed() -> None:
    """os.path.join is not a blocked attribute chain."""
    code = """
import os
path = os.path.join('/tmp', 'data')
"""
    result = check_code(code)
    assert result.safe is True


# ---------------------------------------------------------------------------
# C3: open() blocked
# ---------------------------------------------------------------------------


def test_open_blocked() -> None:
    """Direct open() call is blocked."""
    result = check_code('data = open("/etc/passwd").read()')
    assert not result.safe
    assert any("open" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# C4: Network import blocking
# ---------------------------------------------------------------------------


def test_requests_import_blocked() -> None:
    """Import requests is blocked (must use kernel proxy)."""
    result = check_code("import requests\nrequests.get('http://evil.com')")
    assert not result.safe


def test_urllib_import_blocked() -> None:
    result = check_code("import urllib.request")
    assert not result.safe


def test_urllib3_import_blocked() -> None:
    result = check_code("import urllib3")
    assert not result.safe


def test_httpx_import_blocked() -> None:
    result = check_code("import httpx")
    assert not result.safe


def test_aiohttp_import_blocked() -> None:
    result = check_code("import aiohttp")
    assert not result.safe


def test_http_import_blocked() -> None:
    result = check_code("from http import client")
    assert not result.safe


# Sandbox-escape dunders (object-graph traversal)


def test_class_bases_subclasses_escape_blocked() -> None:
    """The classic ``().__class__.__bases__[0].__subclasses__()`` escape — which
    reaches os/eval without naming a blocked import — is hard-blocked."""
    code = "sink = ().__class__.__bases__[0].__subclasses__()\n"
    result = check_code(code)
    assert not result.safe
    assert any("dunder" in i for i in result.issues)


def test_globals_dunder_blocked() -> None:
    """Access to __globals__ (a route to builtins) is blocked."""
    result = check_code("g = (lambda: 0).__globals__\n")
    assert not result.safe


def test_builtins_dunder_blocked() -> None:
    result = check_code("b = [].__class__.__base__.__subclasses__\n")
    assert not result.safe


def test_plain_attribute_access_still_safe() -> None:
    """A normal (non-dunder) attribute chain is not falsely flagged."""
    code = "import json\nx = json.dumps({'a': 1})\n"
    result = check_code(code)
    assert result.safe
