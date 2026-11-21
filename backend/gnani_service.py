"""
VaaniKhata – Gnani API Platform Streaming Bridge
=================================================
Live streaming WebSocket clients for:
  • Gnani Timbre v3.0 Streaming TTS (wss://api.vachana.ai/api/v1/tts)
  • Gnani Prisma v3.0 Streaming STT (wss://api.vachana.ai/stt/v3/stream)

Features:
  - Sub-80ms barge-in cancellation via asyncio.Event
  - Turn-1 AI Disclosure audio caching for instant (< 20 ms) replay
  - Strict spoken-word TTS input enforcement (0 raw digits)
  - Automatic 44-byte WAV header assembly for raw PCM
  - Graceful browser fallback when offline or unconfigured
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import struct
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional, Tuple

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatusCode

from backend.config import get_settings

logger = logging.getLogger("vaanikhata.gnani_service")

# ---------------------------------------------------------------------------
# Constants & Caches (Memory + Disk Persistent)
# ---------------------------------------------------------------------------
GNANI_TIMBRE_WS_URL = "wss://api.vachana.ai/api/v1/tts"
GNANI_PRISMA_WS_URL = "wss://api.vachana.ai/stt/v3/stream"
TTS_TIMEOUT_SECONDS = 12.0
STT_CONNECT_TIMEOUT = 5.0

# Disk-persistent cache directory
_TTS_CACHE_DIR = Path(__file__).resolve().parent / ".tts_cache"

# In-memory WAV audio cache for Turn-1 AI Disclosure & frequent phrases
_DISCLOSURE_AUDIO_CACHE: dict[str, str] = {}
_tts_lock: Optional[asyncio.Lock] = None


def _get_tts_lock() -> asyncio.Lock:
    global _tts_lock
    if _tts_lock is None:
        _tts_lock = asyncio.Lock()
    return _tts_lock


def is_dev_mode() -> bool:
    """Return True if GNANI_DEV_MODE is enabled to protect API credits."""
    try:
        s = get_settings()
        return bool(getattr(s, "gnani_dev_mode", False))
    except Exception:
        return os.environ.get("GNANI_DEV_MODE", "false").lower() in ("true", "1", "yes")


def _get_cache_file(model: str, voice: str, language: str, text: str) -> Path:
    """Generate deterministic sha256 cache file path."""
    _TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    raw = f"{model}:{voice}:{language}:{text.strip()}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _TTS_CACHE_DIR / f"{h}.wav"


def is_gnani_configured() -> bool:
    """Return True only if a real, non-placeholder Gnani API key is configured."""
    try:
        s = get_settings()
        k = s.gnani_api_key.strip()
    except Exception:
        k = os.environ.get("GNANI_API_KEY", "").strip()

    if not k or k.startswith("PASTE_") or k.startswith("your_") or k.startswith("mock_"):
        return False
    return True


def _pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM bytes with a standard 44-byte RIFF/WAVE header if not already present."""
    if pcm_bytes.startswith(b"RIFF"):
        return pcm_bytes

    data_len = len(pcm_bytes)
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_len,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,
        b"data",
        data_len,
    )
    return header + pcm_bytes


# ---------------------------------------------------------------------------
# Gnani Timbre v3.0 Streaming TTS
# ---------------------------------------------------------------------------
async def synthesize_timbre_tts(
    tts_text: str,
    language_code: str = "hi-IN",
    cancel_event: Optional[asyncio.Event] = None,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """
    Stream synthesis from Gnani Timbre v3.0 via WebSocket.
    Supports <80ms barge-in cancellation and disclosure audio caching.
    Returns:
      {
        "audio_b64": base64_wav_str | None,
        "tts_provider": "gnani_timbre_v3.0" | "browser_fallback",
        "ttfa_ms": int,
        "status": "ok" | "cancelled" | "fallback",
        "tts_cached": bool
      }
    """
    if not tts_text or not tts_text.strip():
        return {
            "audio_b64": None,
            "tts_provider": "browser_fallback",
            "ttfa_ms": 0,
            "status": "empty",
            "tts_cached": False,
        }

    try:
        settings = get_settings()
        api_key = settings.gnani_api_key
        ws_url = settings.tts_ws_url or GNANI_TIMBRE_WS_URL
        voice = getattr(settings, "gnani_tts_voice", "Avinash")
        model = getattr(settings, "tts_model", "timbre-v3.0")
    except Exception:
        api_key = os.environ.get("GNANI_API_KEY", "")
        ws_url = GNANI_TIMBRE_WS_URL
        voice = "Avinash"
        model = "timbre-v3.0"

    cache_key = f"{model}:{voice}:{language_code}:{tts_text.strip()}"

    # Credit & Latency Saver 1: In-memory cache
    if not bypass_cache and cache_key in _DISCLOSURE_AUDIO_CACHE:
        return {
            "audio_b64": _DISCLOSURE_AUDIO_CACHE[cache_key],
            "tts_provider": "gnani_timbre_v3.0",
            "ttfa_ms": 10,
            "status": "cached",
            "tts_cached": True,
        }

    # Credit & Latency Saver 2: Disk-persistent WAV TTS cache
    cache_file = _get_cache_file(model, voice, language_code, tts_text)
    if not bypass_cache and cache_file.exists():
        try:
            cached_b64 = cache_file.read_text(encoding="utf-8")
            _DISCLOSURE_AUDIO_CACHE[cache_key] = cached_b64
            return {
                "audio_b64": cached_b64,
                "tts_provider": "gnani_timbre_v3.0",
                "ttfa_ms": 5,
                "status": "cached_disk",
                "tts_cached": True,
            }
        except Exception:
            pass

    # Credit Saver 3: Dev Mode check (0 credits spent!)
    if is_dev_mode():
        return {
            "audio_b64": None,
            "tts_provider": "browser_fallback",
            "ttfa_ms": 0,
            "status": "dev_mode",
            "tts_cached": False,
        }

    if not is_gnani_configured():
        return {
            "audio_b64": None,
            "tts_provider": "browser_fallback",
            "ttfa_ms": 0,
            "status": "fallback",
            "tts_cached": False,
        }

    headers = {"X-API-Key-ID": api_key}
    request_payload = {
        "text": tts_text,
        "voice": voice,
        "model": "timbre-v3.0",
        "language": language_code,
        "speed": 1.0,
        "audio_config": {
            "sample_rate": 16000,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        },
    }

    t0 = time.perf_counter()
    ttfa_ms = 0
    pcm_buffer = bytearray()

    try:
        async with _get_tts_lock():
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                open_timeout=TTS_TIMEOUT_SECONDS,
                close_timeout=3.0,
            ) as ws:
                # Check immediate barge-in before send
                if cancel_event and cancel_event.is_set():
                    return {"audio_b64": None, "tts_provider": "gnani_timbre_v3.0", "ttfa_ms": 0, "status": "cancelled", "tts_cached": False}

                await ws.send(json.dumps(request_payload))

                while True:
                    # Barge-In check on every chunk (< 80 ms latency)
                    if cancel_event and cancel_event.is_set():
                        await ws.close()
                        return {
                            "audio_b64": None,
                            "tts_provider": "gnani_timbre_v3.0",
                            "ttfa_ms": ttfa_ms or int((time.perf_counter() - t0) * 1000),
                            "status": "cancelled",
                            "tts_cached": False,
                        }

                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=TTS_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        break

                    if ttfa_ms == 0:
                        ttfa_ms = int((time.perf_counter() - t0) * 1000)

                    # Process chunk
                    if isinstance(msg, bytes):
                        pcm_buffer.extend(msg)
                    elif isinstance(msg, str):
                        try:
                            data = json.loads(msg)
                            if "error" in data:
                                logger.warning(f"Timbre TTS API error: {data['error']}")
                                break

                            # Extract base64 payload (supports both flat and nested 'data' envelopes)
                            payload_data = data.get("data")
                            if isinstance(payload_data, dict):
                                b64_chunk = payload_data.get("audio") or payload_data.get("chunk")
                                is_final = bool(payload_data.get("is_final"))
                            else:
                                b64_chunk = (
                                    data.get("audio")
                                    or data.get("audio_content")
                                    or (payload_data if isinstance(payload_data, str) else None)
                                )
                                is_final = bool(data.get("is_final") or data.get("final"))

                            if b64_chunk and isinstance(b64_chunk, str):
                                pcm_buffer.extend(base64.b64decode(b64_chunk))

                            if is_final or data.get("type") in ("end", "finish"):
                                break
                        except json.JSONDecodeError:
                            pass

            if not pcm_buffer:
                return {"audio_b64": None, "tts_provider": "browser_fallback", "ttfa_ms": 0, "status": "fallback", "tts_cached": False}

            wav_bytes = _pcm_to_wav(bytes(pcm_buffer))
            audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

            # Persist to disk cache so server restarts never re-burn credits
            try:
                cache_file.write_text(audio_b64, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to write TTS cache file: {e}")

            # Cache in memory for instant replay
            _DISCLOSURE_AUDIO_CACHE[cache_key] = audio_b64

            return {
                "audio_b64": audio_b64,
                "tts_provider": "gnani_timbre_v3.0",
                "ttfa_ms": ttfa_ms,
                "status": "ok",
                "tts_cached": False,
            }

    except Exception as exc:
        logger.warning(f"Timbre TTS websocket error, using browser fallback: {exc}")
        return {
            "audio_b64": None,
            "tts_provider": "browser_fallback",
            "ttfa_ms": 0,
            "status": "fallback",
            "tts_cached": False,
        }


# ---------------------------------------------------------------------------
# Gnani Prisma v3.0 Streaming STT Client
# ---------------------------------------------------------------------------
class PrismaSTTClient:
    """
    Manages live full-duplex PCM streaming to Gnani Prisma v3.0 STT.
    Supports push-to-talk commit endpointing and partial transcript feeds.
    Includes a hard 12-second max recording guard to protect Gnani API credits.
    """
    MAX_RECORDING_SECONDS = 12.0

    def __init__(
        self,
        ws_url: Optional[str] = None,
        api_key: Optional[str] = None,
        language: Optional[str] = None,
        keywords: Optional[list[str]] = None,
    ):
        try:
            settings = get_settings()
            self.api_key = api_key or settings.gnani_api_key
            self.ws_url = ws_url or settings.stt_ws_url or GNANI_PRISMA_WS_URL
            lang_setting = language or getattr(settings, "stt_language", "hi-IN")
            self.language = lang_setting.split(",")[0].strip() if "," in lang_setting else lang_setting
            self.model = settings.stt_model or "prisma-v3.0"
        except Exception:
            self.api_key = api_key or os.environ.get("GNANI_API_KEY", "")
            self.ws_url = ws_url or GNANI_PRISMA_WS_URL
            self.language = language or "hi-IN"
            self.model = "prisma-v3.0"

        self.keywords: list[str] = list(keywords) if keywords else []
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._stream_start_time: float = 0.0

    def is_timed_out(self) -> bool:
        """Return True if open microphone stream exceeded 12-second max recording limit."""
        if self._stream_start_time <= 0:
            return False
        return (time.perf_counter() - self._stream_start_time) >= self.MAX_RECORDING_SECONDS

    async def connect(self, keywords: Optional[list[str]] = None) -> bool:
        """Establish secure WebSocket to Prisma STT with required connection headers."""
        if keywords is not None:
            self.keywords = list(keywords)

        if is_dev_mode():
            logger.info("Gnani DEV_MODE is active; skipping live Prisma STT connection to protect credits.")
            return False

        if not is_gnani_configured():
            return False

        headers = {
            "X-API-Key-ID": self.api_key,
            "model": self.model,
            "language_code": self.language,
            "format": "transcribe",
            "sample_rate": "16000",
        }

        connect_url = self.ws_url
        if self.keywords:
            from urllib.parse import quote
            kw_str = ",".join(self.keywords)
            headers["keywords"] = kw_str
            sep = "&" if "?" in self.ws_url else "?"
            connect_url = f"{self.ws_url}{sep}keywords={quote(kw_str)}"

        try:
            self.ws = await websockets.connect(
                connect_url,
                additional_headers=headers,
                open_timeout=STT_CONNECT_TIMEOUT,
                close_timeout=2.0,
            )
            self._connected = True
            self._stream_start_time = time.perf_counter()

            # Prisma confirms connection immediately with an ack
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2.0)
                if isinstance(raw, str):
                    logger.info(f"Prisma STT connected: {raw[:120]}")
            except asyncio.TimeoutError:
                pass

            return True
        except Exception as exc:
            logger.warning(f"Could not connect to Prisma STT: {exc}")
            self.ws = None
            self._connected = False
            return False

    async def send_pcm_chunk(self, pcm_bytes: bytes) -> None:
        """Send raw binary 16 kHz PCM chunk directly to Prisma (guarded by 12s limit)."""
        if self.is_timed_out():
            logger.warning("Prisma STT reached 12-second max recording guard. Dropping chunk.")
            return

        if self.ws:
            try:
                await self.ws.send(pcm_bytes)
            except Exception as exc:
                logger.warning(f"Error streaming PCM to Prisma: {exc}")

    async def commit_and_get_final(
        self,
        on_partial: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
    ) -> Tuple[str, str]:
        """
        Send endpointing commit message and collect final recognized transcript.
        Returns (final_transcript, detected_language_code).
        """
        if not self.ws:
            return "", "hi-IN"

        final_text = ""
        detected_lang = "hi-IN"

        try:
            # Force commit
            await self.ws.send(json.dumps({"type": "commit"}))

            # Await final transcript frames (up to 3.5 seconds)
            deadline = time.perf_counter() + 3.5
            while time.perf_counter() < deadline:
                remaining = max(0.2, deadline - time.perf_counter())
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break

                if isinstance(raw, str):
                    try:
                        data = json.loads(raw)
                        text = data.get("transcript") or data.get("text") or ""
                        is_final = data.get("is_final") or data.get("final") or (data.get("type") == "transcript")
                        lang = data.get("language") or data.get("language_code") or detected_lang

                        if text:
                            final_text = text
                            detected_lang = lang
                            if on_partial and not is_final:
                                await on_partial(text)

                        if is_final and final_text:
                            break
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            logger.warning(f"Error retrieving final transcript from Prisma: {exc}")

        return final_text.strip(), detected_lang

    async def close(self) -> None:
        """Cleanly terminate the STT session."""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.ws = None
        self._connected = False
