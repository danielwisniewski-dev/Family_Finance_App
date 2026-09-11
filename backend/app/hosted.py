"""Production WSGI entry point for the private stage 1 beta on Render."""
from __future__ import annotations

import io
import os
from email.message import Message
from http import HTTPStatus
from pathlib import Path

from .api import ApiHandler, MAX_REQUEST_BODY_BYTES
from .backup import BackupScheduler, create_backup
from .coach import build_coach_service_from_env
from .db import BudgetRepository
from .plaid import build_plaid_service_from_env
from .security import RuntimeSettings


class WsgiHandler(ApiHandler):
    """Reuse the tested routes; Waitress owns HTTP parsing, limits, and concurrency."""
    def __init__(self, environ, repository, plaid_service, coach_service):
        self.repository, self.plaid_service, self.coach_service = repository, plaid_service, coach_service
        self.path = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            self.path += "?" + environ["QUERY_STRING"]
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                self.headers[key[5:].replace("_", "-")] = value
        for key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            if environ.get(key):
                self.headers[key.replace("_", "-")] = environ[key]
        self.rfile = environ["wsgi.input"]
        self.wfile = io.BytesIO()
        self.response_headers = []
        self.status = HTTPStatus.INTERNAL_SERVER_ERROR

    def send_response(self, code, message=None):
        self.status = HTTPStatus(code)

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        if self.repository.settings.hosted:
            self.response_headers.append(("Strict-Transport-Security", "max-age=31536000"))
        self.response_headers.append(("X-Frame-Options", "DENY"))


class Application:
    def __init__(self, repository: BudgetRepository, backups: BackupScheduler | None = None):
        self.repository = repository
        self.backups = backups
        self.plaid = build_plaid_service_from_env(repository)
        self.coach = build_coach_service_from_env()

    def __call__(self, environ, start_response):
        handler = WsgiHandler(environ, self.repository, self.plaid, self.coach)
        try:
            if environ.get("REQUEST_METHOD") == "GET" and environ.get("PATH_INFO") == "/ready":
                with self.repository.connect() as connection:
                    connection.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
                healthy = self.backups is not None and self.backups.healthy()
                handler.send_json({"ok": healthy}, HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE)
            elif environ.get("REQUEST_METHOD") in {"GET", "POST", "PATCH", "DELETE"}:
                getattr(handler, "do_" + environ["REQUEST_METHOD"])()
            else:
                handler.send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
        except Exception:
            handler.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Backend error")
        start_response(f"{handler.status.value} {handler.status.phrase}", handler.response_headers)
        return [handler.wfile.getvalue()]


def prepare_application() -> Application:
    settings = RuntimeSettings.from_env()
    if not settings.hosted:
        raise RuntimeError("The hosted entry point requires FF_MODE=hosted")
    db_path = Path(os.environ.get("FF_DB_PATH", "/var/data/family-finance.sqlite"))
    directory = Path(os.environ.get("FF_BACKUP_DIR", "/var/data/backups"))
    if not db_path.is_absolute() or not directory.is_absolute():
        raise ValueError("Hosted database and backup paths must be absolute")
    # Save the old database BEFORE any upgrade. Never migrate an existing personal file in place without recovery.
    if db_path.exists():
        import uuid
        create_backup(db_path, directory / ("pre-upgrade-" + uuid.uuid4().hex + ".ffbackup"), settings.encryption_key)
    repository = BudgetRepository(db_path, settings)
    repository.initialize()
    backups = BackupScheduler(db_path, directory, settings.encryption_key)
    application = Application(repository, backups)
    backups.start()
    previous = sorted(directory.glob("pre-upgrade-*.ffbackup"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in previous[3:]:
        if old.is_file() and not old.is_symlink():
            old.unlink()
    return application


def main():
    from waitress import serve
    try:
        application = prepare_application()
    except Exception:
        raise SystemExit("Hosted startup failed. Check configuration, migration state, encryption key, and backups; existing data was preserved.")
    try:
        serve(application, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
              threads=4, connection_limit=50, channel_timeout=30, cleanup_interval=5,
              max_request_body_size=MAX_REQUEST_BODY_BYTES, max_request_header_size=16384,
              expose_tracebacks=False, clear_untrusted_proxy_headers=True, ident="FamilyFinance")
    finally:
        application.backups.stop_event.set()


if __name__ == "__main__":
    main()
