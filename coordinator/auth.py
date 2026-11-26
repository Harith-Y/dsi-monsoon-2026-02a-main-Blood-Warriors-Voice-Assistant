"""Coordinator sign-in for /dashboard and /teach: one shared numeric passcode from .env (demo-level access).

The passcode is digits only, so a coordinator can say it ("four eight two six", in Telugu, Hindi or English)
or tap it on the on-screen keypad; nobody has to type. A signed-in browser holds an HttpOnly cookie whose
value is an HMAC of the passcode, so changing the passcode signs everyone out.
"""

import hashlib
import hmac
import re
import time
from collections import defaultdict, deque

import config

COOKIE = "bw_coord"
COOKIE_MAX_AGE_S = 12 * 3600
MAX_FAILURES = 5          # wrong tries allowed per client...
FAILURE_WINDOW_S = 60     # ...within this many seconds, then they wait
_failures: dict[str, deque] = defaultdict(deque)


def passcode() -> str | None:
    """The configured passcode as digits, or None when sign-in is not set up (missing or not 4+ digits)."""
    code = re.sub(r"[\s-]", "", config.COORDINATOR_PASSCODE or "")
    return code if code.isdigit() and len(code) >= 4 else None


def session_token() -> str | None:
    code = passcode()
    if not code:
        return None
    return hmac.new(code.encode(), b"bw-coordinator-session", hashlib.sha256).hexdigest()


def check(digits: str) -> bool:
    code = passcode()
    return bool(code) and hmac.compare_digest(digits or "", code)


def valid_session(token: str | None) -> bool:
    expected = session_token()
    return bool(expected and token) and hmac.compare_digest(token, expected)


def locked(client: str) -> bool:
    q = _failures[client]
    cutoff = time.monotonic() - FAILURE_WINDOW_S
    while q and q[0] < cutoff:
        q.popleft()
    return len(q) >= MAX_FAILURES


def record_failure(client: str) -> None:
    _failures[client].append(time.monotonic())


def clear_failures(client: str) -> None:
    _failures.pop(client, None)
