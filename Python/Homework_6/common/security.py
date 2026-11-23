"""JWT authentication and password hashing shared as source code at build time."""
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
import hmac
import os

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


bearer = HTTPBearer(auto_error=False)


class Actor(BaseModel):
    id: int
    login: str
    department_id: int
    role: str


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def create_access_token(actor: Actor, secret: str) -> str:
    payload = {
        "sub": str(actor.id), "login": actor.login,
        "department_id": actor.department_id, "role": actor.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def current_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Actor:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer access token required")
    try:
        data = jwt.decode(credentials.credentials, request.app.state.settings.jwt_secret, algorithms=["HS256"])
        return Actor(
            id=int(data["sub"]), login=data["login"],
            department_id=int(data["department_id"]), role=data["role"],
        )
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


def require_service_key(request: Request) -> None:
    supplied = request.headers.get("X-Service-Token", "")
    expected = request.app.state.settings.service_api_key
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid service token")
