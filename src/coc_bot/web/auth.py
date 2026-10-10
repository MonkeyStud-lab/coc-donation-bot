"""Password hashing, expiring sessions and bounded login throttling."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
import threading
from collections import OrderedDict


def set_password(path: Path, password: str):
    if len(password) < 12:
        raise ValueError("Use a password with at least 12 characters.")
    salt = secrets.token_bytes(32)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".new")
    # Restrict before writing; avoid a briefly world-readable password verifier.
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"salt": salt.hex(), "hash": digest.hex()}, handle)
    os.replace(temp, path)
    os.chmod(path, 0o600)


class Authentication:
    def __init__(self, path, lifetime=8*3600, password_required=True):
        self.path, self.lifetime = path, lifetime
        self.password_required = password_required
        self.sessions = OrderedDict()
        self.attempts = OrderedDict()
        self.lock = threading.RLock()

    def login(self, password, address):
        if not self.password_required:
            return self.open_session()
        with self.lock:
            return self._login(password, address)

    def _login(self, password, address):
        now = time.monotonic()
        attempts = [t for t in self.attempts.get(address, []) if now-t < 60]
        if len(attempts) >= 5:
            raise ValueError("Too many login attempts. Wait one minute.")
        attempts.append(now)
        self.attempts[address] = attempts
        while len(self.attempts) > 512:
            self.attempts.popitem(last=False)
        record = json.loads(self.path.read_text(encoding="utf-8"))
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record["salt"]),
                                n=16384, r=8, p=1)
        if not hmac.compare_digest(digest.hex(), record["hash"]):
            raise ValueError("Incorrect password")
        self.attempts.pop(address, None)
        return self._issue_session(now)

    def open_session(self):
        """Bootstrap a CSRF-protected browser session in explicit password-free mode."""
        if self.password_required:
            raise ValueError("Password required")
        with self.lock:
            return self._issue_session(time.monotonic())

    def _issue_session(self, now):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.sessions[token] = (now+self.lifetime, csrf)
        while len(self.sessions) > 64:
            self.sessions.popitem(last=False)
        return token, csrf

    def session(self, token):
        with self.lock:
            return self._session(token)

    def _session(self, token):
        record = self.sessions.get(token)
        if not record or record[0] <= time.monotonic():
            self.sessions.pop(token, None)
            return None
        return record[1]

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)
