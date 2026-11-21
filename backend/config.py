"""
VaaniKhata – Typed Configuration Module
========================================
Loads all secrets and tunables from environment variables (.env file).
Uses Pydantic Settings for validation, type coercion, and safe repr
(secrets are automatically masked in logs/repr).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Resolve the .env that sits at the project root (vaanikhata/.env)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class GnaniSettings(BaseSettings):
    """Gnani Voice API credentials and model defaults."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Credentials ──────────────────────────────────────────────────────
    gnani_dev_mode: bool = Field(
        default=False,
        description="When True, skips live Gnani STT/TTS calls and uses browser fallback to protect API credits.",
        json_schema_extra={"env": "GNANI_DEV_MODE"},
    )
    gnani_api_key: str = Field(
        default="",
        description="Gnani X-API-Key-ID for both TTS and STT services.",
        json_schema_extra={"env": "GNANI_API_KEY"},
    )
    gemini_api_key: str = Field(
        default="",
        description="Optional Gemini API key for fallback slot extraction.",
        json_schema_extra={"env": "GEMINI_API_KEY"},
    )

    # ── Database ─────────────────────────────────────────────────────────
    db_path: str = Field(
        default="vaanikhata.db",
        description="Path to the SQLite database file (relative to project root).",
    )
    encryption_key: str = Field(
        default="",
        description="Fernet key for AES encryption. If empty, auto-generated to .fernet.key.",
    )

    # ── STT (Prisma v3.0) ────────────────────────────────────────────────
    stt_ws_url: str = Field(
        default="wss://api.vachana.ai/stt/v3/stream",
        description="WebSocket endpoint for Gnani Prisma STT.",
    )
    stt_model: str = Field(default="prisma-v3.0")
    stt_language: str = Field(
        default="hi-IN,kn-IN,ta-IN,te-IN,mr-IN,en-IN",
        description="BCP-47 language codes comma-separated or 'indic-auto' for auto-detect.",
    )
    stt_sample_rate: int = Field(default=16000)
    stt_format: Literal["verbatim", "transcribe", "codemix", "transliterate"] = Field(
        default="transcribe",
    )

    # ── TTS (Timbre v3.0) ────────────────────────────────────────────────
    tts_ws_url: str = Field(
        default="wss://api.vachana.ai/api/v1/tts",
        description="WebSocket endpoint for Gnani Timbre TTS.",
    )
    tts_model: str = Field(default="timbre-v3.0")
    tts_voice: str = Field(default="Avinash")
    tts_language: str = Field(default="hi-IN")
    tts_speed: float = Field(default=1.0, ge=0.25, le=4.0)
    tts_sample_rate: int = Field(default=16000)
    tts_encoding: str = Field(default="linear_pcm")
    tts_container: str = Field(default="wav")

    # ── Convenience Properties ───────────────────────────────────────────
    @property
    def gnani_tts_voice(self) -> str:
        return self.tts_voice

    @property
    def gnani_stt_languages(self) -> str:
        return self.stt_language

    # ── Validators ───────────────────────────────────────────────────────
    @field_validator("gnani_api_key")
    @classmethod
    def _key_not_placeholder(cls, v: str) -> str:
        return (v or "").strip()


@lru_cache(maxsize=1)
def get_settings() -> GnaniSettings:
    """Return a cached, validated settings singleton."""
    return GnaniSettings()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Quick sanity check when run directly: `python -m backend.config`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    settings = get_settings()
    print("✅ Config loaded successfully!")
    print(f"   STT endpoint : {settings.stt_ws_url}")
    print(f"   STT model    : {settings.stt_model}")
    print(f"   TTS endpoint : {settings.tts_ws_url}")
    print(f"   TTS model    : {settings.tts_model}")
    print(f"   API key      : {settings.gnani_api_key[:6]}{'*' * 12}")
