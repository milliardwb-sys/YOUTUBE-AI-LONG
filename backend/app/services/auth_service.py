from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from app.config import Settings
from app.models import AuthToken, PlatformUser, UserCreate, UserLogin, UserSession
from app.utils.files import ensure_dir, read_json, write_json


class AuthError(RuntimeError):
    pass


class UserAlreadyExistsError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class SessionNotFoundError(AuthError):
    pass


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.auth_dir = ensure_dir(settings.data_dir / "_auth")
        self.users_dir = ensure_dir(self.auth_dir / "users")
        self.sessions_dir = ensure_dir(self.auth_dir / "sessions")
        self._lock = Lock()

    def register(self, payload: UserCreate) -> AuthToken:
        with self._lock:
            if self.find_user_by_email(payload.email) is not None:
                raise UserAlreadyExistsError("User already exists")
            user = PlatformUser(
                email=payload.email,
                name=payload.name,
                password_hash=_hash_password(payload.password),
            )
            self._save_user(user)
        return self.create_session(user)

    def login(self, payload: UserLogin) -> AuthToken:
        user = self.find_user_by_email(payload.email)
        if user is None or user.disabled or not _verify_password(payload.password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")
        return self.create_session(user)

    def create_session(self, user: PlatformUser) -> AuthToken:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.settings.access_token_ttl_minutes)
        session = UserSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=expires_at,
        )
        self._save_session(session)
        return AuthToken(access_token=token, expires_at=expires_at, user=user.public())

    def get_user_by_token(self, token: str) -> PlatformUser:
        token_hash = _hash_token(token)
        now = datetime.now(timezone.utc)
        for path in sorted(self.sessions_dir.glob("session_*.json")):
            try:
                session = UserSession.model_validate(read_json(path))
            except Exception:
                continue
            if session.expires_at <= now:
                path.unlink(missing_ok=True)
                continue
            if hmac.compare_digest(session.token_hash, token_hash):
                user = self.get_user(session.user_id)
                if user.disabled:
                    raise InvalidCredentialsError("User is disabled")
                return user
        raise SessionNotFoundError("Session not found")

    def revoke_token(self, token: str) -> bool:
        token_hash = _hash_token(token)
        with self._lock:
            for path in sorted(self.sessions_dir.glob("session_*.json")):
                try:
                    session = UserSession.model_validate(read_json(path))
                except Exception:
                    continue
                if hmac.compare_digest(session.token_hash, token_hash):
                    path.unlink(missing_ok=True)
                    return True
        return False

    def cleanup_expired_sessions(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        removed = 0
        skipped = 0
        with self._lock:
            for path in sorted(self.sessions_dir.glob("session_*.json")):
                try:
                    session = UserSession.model_validate(read_json(path))
                except Exception:
                    path.unlink(missing_ok=True)
                    removed += 1
                    continue
                if session.expires_at <= now:
                    path.unlink(missing_ok=True)
                    removed += 1
                else:
                    skipped += 1
        return {"removed_sessions": removed, "skipped_sessions": skipped}

    def get_user(self, user_id: str) -> PlatformUser:
        path = self._user_file(user_id)
        if not path.exists():
            raise InvalidCredentialsError("User not found")
        return PlatformUser.model_validate(read_json(path))

    def find_user_by_email(self, email: str) -> PlatformUser | None:
        clean = email.strip().lower()
        for path in sorted(self.users_dir.glob("user_*.json")):
            try:
                user = PlatformUser.model_validate(read_json(path))
            except Exception:
                continue
            if user.email == clean:
                return user
        return None

    def _user_file(self, user_id: str) -> Path:
        return self.users_dir / f"{user_id}.json"

    def _session_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _save_user(self, user: PlatformUser) -> None:
        user.updated_at = datetime.now(timezone.utc)
        write_json(self._user_file(user.id), user.model_dump(mode="json"))

    def _save_session(self, session: UserSession) -> None:
        write_json(self._session_file(session.id), session.model_dump(mode="json"))


def _hash_password(password: str, *, iterations: int = 200_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = password_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return hmac.compare_digest(digest, expected)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
