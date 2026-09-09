from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = "sqlite:///./g-one.db"
    jwt_secret: str = "development-only-secret-change-me"
    jwt_issuer: str = "g-one"
    jwt_audience: str = "g-one-api"
    console_password: str = "development-console-password"
    environment: str = "development"

    @classmethod
    def from_environment(cls) -> "Settings":
        defaults = cls()
        settings = cls(
            database_url=os.getenv("G_ONE_DATABASE_URL", defaults.database_url),
            jwt_secret=os.getenv("G_ONE_JWT_SECRET", defaults.jwt_secret),
            jwt_issuer=os.getenv("G_ONE_JWT_ISSUER", defaults.jwt_issuer),
            jwt_audience=os.getenv("G_ONE_JWT_AUDIENCE", defaults.jwt_audience),
            console_password=os.getenv("G_ONE_CONSOLE_PASSWORD", defaults.console_password),
            environment=os.getenv("G_ONE_ENVIRONMENT", defaults.environment),
        )
        if settings.environment != "development" and settings.jwt_secret == defaults.jwt_secret:
            raise RuntimeError("G_ONE_JWT_SECRET must be set outside development")
        if (
            settings.environment != "development"
            and settings.console_password == defaults.console_password
        ):
            raise RuntimeError("G_ONE_CONSOLE_PASSWORD must be set outside development")
        if len(settings.jwt_secret.encode()) < 32:
            raise RuntimeError("G_ONE_JWT_SECRET must contain at least 32 bytes")
        if len(settings.console_password) < 16:
            raise RuntimeError("G_ONE_CONSOLE_PASSWORD must contain at least 16 characters")
        return settings
