"""Env-driven settings for the Kansallisarkisto MCP server."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from ra_mcp_kansallisarkisto_lib.config import resolve_lancedb_uri


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Empty means "resolve at use time" (project data/ in development, /data in the
    # image) — see ra_mcp_kansallisarkisto_lib.config.
    ka_lancedb_uri: str = ""
    ka_mcp_transport: str = "stdio"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    @property
    def lancedb_uri(self) -> str:
        return self.ka_lancedb_uri.strip() or resolve_lancedb_uri()


settings = Settings()
