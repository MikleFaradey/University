"""Configuration read from the environment supplied by docker-compose/.env."""
from dataclasses import dataclass
from os import environ


@dataclass(frozen=True)
class Settings:
    service_name: str
    db_path: str
    jwt_secret: str
    service_api_key: str
    notification_url: str
    audit_url: str
    retry_interval_seconds: float
    deadline_scan_seconds: float
    request_timeout_seconds: float
    bootstrap_admin_login: str
    bootstrap_admin_password: str


def load_settings(service_name: str) -> Settings:
    prefix = {"task": "TASK", "notification": "NOTIFICATION", "audit": "AUDIT"}[service_name]
    settings = Settings(
        service_name=service_name,
        db_path=environ.get(f"{prefix}_DB_PATH", f"/data/{service_name}.db"),
        jwt_secret=environ.get("JWT_SECRET", "local-test-jwt-secret-change-me"),
        service_api_key=environ.get("SERVICE_API_KEY", "local-test-service-key-change-me"),
        notification_url=environ.get("NOTIFICATION_URL", "http://notification:8002"),
        audit_url=environ.get("AUDIT_URL", "http://audit:8003"),
        retry_interval_seconds=float(environ.get("OUTBOX_RETRY_SECONDS", "15")),
        deadline_scan_seconds=float(environ.get("DEADLINE_SCAN_SECONDS", "300")),
        request_timeout_seconds=float(environ.get("HTTP_TIMEOUT_SECONDS", "1.5")),
        bootstrap_admin_login=environ.get("BOOTSTRAP_ADMIN_LOGIN", "admin"),
        bootstrap_admin_password=environ.get("BOOTSTRAP_ADMIN_PASSWORD", "change-me-before-deploy"),
    )
    if settings.request_timeout_seconds <= 0 or settings.retry_interval_seconds < 0 or settings.deadline_scan_seconds < 0:
        raise ValueError("Timeout must be positive and intervals nonnegative")
    return settings
