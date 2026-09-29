"""Disposable demo sessions. Never selects or changes a production repository."""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .coach import build_coach_service_from_env
from .security import RateLimitError


class DemoSessionExpired(Exception):
    pass


def _lock_owner(handle, *, blocking=False) -> None:
    """Hold a nonblocking OS lock; a crashed process releases it automatically."""
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


class _OwnedDemoRoot:
    PREFIX = "ledger-demo-sessions-"
    MARKER = ".ledger-demo-owner"
    MAGIC = "Ledger disposable demo session root v1\n"

    def __init__(self):
        self.prune_orphans()
        self.parent = Path(tempfile.gettempdir()).resolve()
        self.name = tempfile.mkdtemp(prefix=self.PREFIX)
        root = Path(self.name)
        self.owner = (root / self.MARKER).open("x+b")
        # Acquire before writing the marker, so a concurrent janitor cannot
        # mistake a root still being created for an abandoned root.
        self.owner.write(b" ")
        self.owner.flush()
        _lock_owner(self.owner, blocking=True)
        self.owner.seek(0)
        self.owner.write((self.MAGIC + root.name + "\n").encode("ascii"))
        self.owner.flush()

    @classmethod
    def prune_orphans(cls) -> None:
        parent = Path(tempfile.gettempdir()).resolve()
        for root in parent.glob(cls.PREFIX + "*"):
            marker = root / cls.MARKER
            try:
                # Never follow a directory/marker symlink or remove a directory
                # without the exact ownership marker produced by this class.
                if (root.is_symlink() or not root.is_dir() or root.resolve().parent != parent
                        or marker.is_symlink() or not marker.is_file()):
                    continue
                with marker.open("r+b") as owner:
                    _lock_owner(owner)
                    owner.seek(0)
                    if owner.read(256) != (cls.MAGIC + root.name + "\n").encode("ascii"):
                        continue
                # Managers never adopt old roots. Closing the lock before
                # deletion is necessary on Windows; competing janitors are safe
                # because none can turn this orphan into an active workspace.
                if not root.is_symlink() and root.resolve().parent == parent:
                    shutil.rmtree(root)
            except OSError:
                # A live owner holds the lock, another janitor won the race, or
                # storage is temporarily busy. Retry on a later sweep/start.
                continue

    def cleanup(self) -> None:
        self.owner.close()
        root = Path(self.name)
        if root.is_symlink() or root.resolve().parent != self.parent or not root.name.startswith(self.PREFIX):
            raise RuntimeError("Demo root is outside its owned temporary directory")
        try:
            shutil.rmtree(root)
        except FileNotFoundError:
            pass


@dataclass
class DemoSession:
    context: Any
    directory: Path
    expires_at: float
    deadline: float
    coach_service: Any
    lock: Any = field(default_factory=threading.RLock)
    retired: bool = False


class DemoSessionManager:
    """One bounded registry per server; every request holds its session's lock.

    Tokens are indexed by hash. Directories have server-generated names under a
    private temporary root, never a client path or the household database path.
    Cleanup cannot race an in-flight write. A restart invalidates all demo tokens.
    """

    def __init__(self, *, ttl_seconds: int = 8 * 60 * 60, max_sessions: int = 8,
                 factory: Callable | None = None):
        if ttl_seconds <= 0 or max_sessions <= 0:
            raise ValueError("Demo limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._factory = factory
        self._lock = threading.RLock()
        self._sessions: dict[str, DemoSession] = {}
        self._pending_directories: set[Path] = set()
        self._starts: dict[tuple[int, int], list[float]] = {}
        self._temporary = None
        self._stop = threading.Event()
        self._sweeper = None

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def start(self, owner: dict[str, Any]) -> dict[str, Any]:
        self.prune()
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("Demo service is unavailable")
            now = time.monotonic()
            self._starts = {key: [stamp for stamp in stamps if now - stamp < 60]
                            for key, stamps in self._starts.items() if any(now - stamp < 60 for stamp in stamps)}
            identity = (owner["household_id"], owner["user_id"])
            attempts = self._starts.setdefault(identity, [])
            if len(attempts) >= 4:
                raise RateLimitError("Please wait before starting another demo")
            if len(self._sessions) + len(self._pending_directories) >= self.max_sessions:
                raise RateLimitError("Demo sessions are busy. Leave an open demo or try again later.")
            attempts.append(now)
            if self._temporary is None:
                self._temporary = _OwnedDemoRoot()
            directory = Path(self._temporary.name) / secrets.token_hex(16)
            directory.mkdir(mode=0o700)
            try:
                if self._factory is None:
                    from .demo_data import create_demo_context
                    factory = create_demo_context
                else:
                    factory = self._factory
                context = factory(directory / "demo.sqlite")
                login = dict(context.login)
                expires_at = time.time() + self.ttl_seconds
                session = DemoSession(context, directory, expires_at,
                    time.monotonic() + self.ttl_seconds,
                    build_coach_service_from_env({"COACH_PROVIDER": "mock"}))
                self._sessions[self._key(login["token"])] = session
                login.update(demo=True, budget_month_id=context.budget_month_id,
                    expires_at=datetime.fromtimestamp(expires_at, timezone.utc).isoformat())
                if self._sweeper is None:
                    self._sweeper = threading.Thread(target=self._sweep, name="ledger-demo-cleanup", daemon=True)
                    self._sweeper.start()
                return login
            except Exception:
                try:
                    self._remove_directory(directory)
                except OSError:
                    self._pending_directories.add(directory)
                raise

    @contextmanager
    def use(self, token: str):
        with self._lock:
            if self._stop.is_set():
                raise DemoSessionExpired()
            session = self._sessions.get(self._key(token))
        if session is None:
            raise DemoSessionExpired()
        with session.lock:
            if session.retired or session.deadline <= time.monotonic():
                self.retire(token)
                raise DemoSessionExpired()
            yield session

    def retire(self, token: str) -> None:
        key = self._key(token)
        with self._lock:
            session = self._sessions.get(key)
        if session is not None:
            with session.lock:
                self._retire_locked(key, session)

    def _retire_locked(self, key: str, session: DemoSession) -> None:
        session.retired = True
        try:
            self._remove_directory(session.directory)
        except OSError:
            # Keep an invalid tombstone and its capacity slot until storage can
            # be removed. A transient deletion failure must not orphan a DB.
            return
        with self._lock:
            if self._sessions.get(key) is session:
                self._sessions.pop(key)

    def _remove_directory(self, directory: Path) -> None:
        if self._temporary is None:
            raise RuntimeError("Demo cleanup has no owned directory")
        root = Path(self._temporary.name).resolve()
        if directory.is_symlink() or directory.resolve().parent != root:
            raise RuntimeError("Demo cleanup path is outside its owned directory")
        if directory.exists():
            shutil.rmtree(directory)

    def prune(self) -> None:
        with self._lock:
            for directory in tuple(self._pending_directories):
                try:
                    self._remove_directory(directory)
                except OSError:
                    continue
                self._pending_directories.discard(directory)
            expired = [(key, item) for key, item in self._sessions.items()
                       if item.retired or item.deadline <= time.monotonic()]
        for key, item in expired:
            with item.lock:
                self._retire_locked(key, item)

    def _sweep(self) -> None:
        while not self._stop.wait(60):
            try:
                self.prune()
                _OwnedDemoRoot.prune_orphans()
            except Exception:
                # Retain tracked data for another attempt; a cleanup error must
                # never permanently stop expiry for all other demo sessions.
                continue

    def close(self) -> None:
        self._stop.set()
        if self._sweeper is not None and self._sweeper is not threading.current_thread():
            self._sweeper.join(timeout=1)
        with self._lock:
            sessions = list(self._sessions.items())
        for key, item in sessions:
            with item.lock:
                self._retire_locked(key, item)
        if self._temporary is not None:
            try:
                self._temporary.cleanup()
            except OSError:
                # Released owner lock allows a future manager's orphan sweep
                # to finish even when shutdown cannot delete a busy file.
                pass


def demo_routes(method):
    """Route normal handlers using only per-request context, on both HTTP hosts."""
    from functools import wraps
    from http import HTTPStatus
    from urllib.parse import urlparse

    @wraps(method)
    def dispatch(handler):
        path = urlparse(handler.path).path
        manager = getattr(handler, "demo_manager", None)
        if path != "/demo" and not path.startswith("/demo/"):
            return method(handler)
        previous_demo = getattr(handler, "is_demo", False)
        handler.is_demo = True
        try:
            if manager is None:
                handler.send_error_json(HTTPStatus.SERVICE_UNAVAILABLE, "Demo mode is unavailable")
                return
            if path == "/demo/start" and method.__name__ == "do_POST":
                owner = handler.require_auth()
                handler.read_json()
                handler.send_json(manager.start(owner))
                return
            header = handler.headers.get("Authorization", "")
            scheme, _, token = header.partition(" ")
            if scheme.casefold() != "bearer" or not token.strip():
                raise DemoSessionExpired()
            token = token.strip()
            with manager.use(token) as session:
                previous = (handler.path, handler.repository, handler.plaid_service, handler.coach_service)
                handler.path = handler.path[len("/demo"):]
                handler.repository = session.context.repository
                handler.plaid_service = session.context.plaid_service
                handler.coach_service = session.coach_service
                try:
                    from .api import UnauthorizedError
                    try:
                        handler.require_auth()
                    except UnauthorizedError:
                        manager.retire(token)
                        raise DemoSessionExpired()
                    if path in {"/demo/exit", "/demo/auth/logout"} and method.__name__ == "do_POST":
                        handler.read_json()
                        manager.retire(token)
                        handler.send_json({"ok": True})
                    elif path in {"/demo/auth/login", "/demo/setup/initialize", "/demo/settings/password"}:
                        handler.send_error_json(HTTPStatus.FORBIDDEN, "Leave demo mode to manage your real login.")
                    else:
                        method(handler)
                finally:
                    handler.path, handler.repository, handler.plaid_service, handler.coach_service = previous
        except DemoSessionExpired:
            handler.send_error_json(HTTPStatus.UNAUTHORIZED,
                "This demo has ended. Leave demo mode and turn it on again for fresh sample data.", code="demo_session_expired")
        except Exception as exc:
            handler.send_exception(exc)
        finally:
            handler.is_demo = previous_demo
    return dispatch
