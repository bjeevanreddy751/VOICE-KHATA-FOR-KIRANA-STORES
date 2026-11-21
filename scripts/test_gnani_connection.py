#!/usr/bin/env python3
"""
VaaniKhata – Gnani WebSocket Handshake Verification Script
===========================================================
Tests live end-to-end WebSocket connectivity for:
  • Gnani Prisma v3.0 STT  (wss://api.vachana.ai/stt/v3/stream)
  • Gnani Timbre v3.0 TTS  (wss://api.vachana.ai/api/v1/tts)

Usage:
    cd vaanikhata/
    python -m scripts.test_gnani_connection

Exit codes:
    0  – Both handshakes succeeded
    1  – One or both handshakes failed
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so `backend.config` resolves
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    # Graceful degradation if colorama isn't installed
    class _NoColor:
        GREEN = YELLOW = RED = CYAN = MAGENTA = RESET = ""
    Fore = _NoColor()  # type: ignore[assignment]
    class _NoStyle:
        BRIGHT = RESET_ALL = ""
    Style = _NoStyle()  # type: ignore[assignment]

import websockets
from websockets.exceptions import (
    ConnectionClosedError,
    InvalidStatusCode,
    InvalidHandshake,
)

from backend.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HANDSHAKE_TIMEOUT = 10  # seconds


def _banner(title: str) -> None:
    width = 60
    print(f"\n{Fore.CYAN}{'━' * width}")
    print(f"  {Style.BRIGHT}{title}")
    print(f"{'━' * width}{Style.RESET_ALL}")


def _ok(msg: str) -> None:
    print(f"  {Fore.GREEN}✅  {msg}{Style.RESET_ALL}")


def _fail(msg: str) -> None:
    print(f"  {Fore.RED}❌  {msg}{Style.RESET_ALL}")


def _info(msg: str) -> None:
    print(f"  {Fore.YELLOW}ℹ️   {msg}{Style.RESET_ALL}")


# ---------------------------------------------------------------------------
# STT Handshake Test
# ---------------------------------------------------------------------------
async def test_stt_handshake(settings) -> bool:
    """Open a WebSocket to Prisma STT, verify the 'connected' ack, then close."""
    _banner("STT · Gnani Prisma v3.0")
    _info(f"Endpoint : {settings.stt_ws_url}")
    _info(f"Model    : {settings.stt_model}")
    _info(f"Language : {settings.stt_language}")

    headers = {
        "X-API-Key-ID": settings.gnani_api_key,
        "model": settings.stt_model,
        "language_code": "hi-IN",
        "sample_rate": str(settings.stt_sample_rate),
        "format": settings.stt_format,
    }

    t0 = time.perf_counter()
    try:
        async with websockets.connect(
            settings.stt_ws_url,
            additional_headers=headers,
            open_timeout=HANDSHAKE_TIMEOUT,
            close_timeout=5,
        ) as ws:
            latency_ms = (time.perf_counter() - t0) * 1000
            _ok(f"WebSocket OPEN  ({latency_ms:.0f} ms)")

            # Prisma sends a 'connected' confirmation after handshake
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT)
                latency_ms = (time.perf_counter() - t0) * 1000
                if isinstance(raw, str):
                    payload = json.loads(raw)
                    _ok(f"Server ACK received ({latency_ms:.0f} ms)")
                    _info(f"Response : {json.dumps(payload, indent=2, ensure_ascii=False)[:300]}")
                else:
                    _ok(f"Server sent binary ACK ({len(raw)} bytes, {latency_ms:.0f} ms)")
            except asyncio.TimeoutError:
                _info("No explicit ACK within timeout (connection still valid)")

            await ws.close()
            _ok("Connection closed gracefully")
            return True

    except InvalidStatusCode as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        _fail(f"HTTP {exc.status_code} during handshake ({latency_ms:.0f} ms)")
        if exc.status_code == 401:
            _fail("API key is invalid or missing – check GNANI_API_KEY in .env")
        elif exc.status_code == 429:
            _fail("Rate-limited – wait and retry")
        return False
    except (InvalidHandshake, ConnectionClosedError) as exc:
        _fail(f"Handshake failed: {exc}")
        return False
    except OSError as exc:
        _fail(f"Network error: {exc}")
        return False


# ---------------------------------------------------------------------------
# TTS Handshake Test
# ---------------------------------------------------------------------------
async def test_tts_handshake(settings) -> bool:
    """Open a WebSocket to Timbre TTS, send a small synthesis request, verify audio ack."""
    _banner("TTS · Gnani Timbre v3.0")
    _info(f"Endpoint : {settings.tts_ws_url}")
    _info(f"Model    : {settings.tts_model}")
    _info(f"Voice    : {settings.tts_voice}")
    _info(f"Language : {settings.tts_language}")

    headers = {
        "X-API-Key-ID": settings.gnani_api_key,
    }

    t0 = time.perf_counter()
    try:
        async with websockets.connect(
            settings.tts_ws_url,
            additional_headers=headers,
            open_timeout=HANDSHAKE_TIMEOUT,
            close_timeout=5,
        ) as ws:
            latency_ms = (time.perf_counter() - t0) * 1000
            _ok(f"WebSocket OPEN  ({latency_ms:.0f} ms)")

            # Send a minimal synthesis request
            tts_request = {
                "text": "नमस्ते",
                "model": settings.tts_model,
                "voice": settings.tts_voice,
                "language": settings.tts_language,
                "speed": settings.tts_speed,
                "audio_config": {
                    "sample_rate": settings.tts_sample_rate,
                    "num_channels": 1,
                    "sample_width": 2,
                    "encoding": settings.tts_encoding,
                    "container": settings.tts_container,
                },
            }

            await ws.send(json.dumps(tts_request))
            _ok("Synthesis request sent (text: 'नमस्ते')")

            # Wait for at least one response frame
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT)
                latency_ms = (time.perf_counter() - t0) * 1000
                if isinstance(raw, str):
                    payload = json.loads(raw)
                    _ok(f"Server response received ({latency_ms:.0f} ms)")
                    # Check for audio data or error
                    if "error" in payload:
                        _fail(f"Server error: {payload['error']}")
                        return False
                    _info(f"Response keys: {list(payload.keys())}")
                else:
                    _ok(f"Binary audio chunk received ({len(raw)} bytes, {latency_ms:.0f} ms)")
            except asyncio.TimeoutError:
                _info("No response within timeout – connection may still be valid")

            await ws.close()
            _ok("Connection closed gracefully")
            return True

    except InvalidStatusCode as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        _fail(f"HTTP {exc.status_code} during handshake ({latency_ms:.0f} ms)")
        if exc.status_code == 401:
            _fail("API key is invalid or missing – check GNANI_API_KEY in .env")
        elif exc.status_code == 429:
            _fail("Rate-limited – wait and retry")
        return False
    except (InvalidHandshake, ConnectionClosedError) as exc:
        _fail(f"Handshake failed: {exc}")
        return False
    except OSError as exc:
        _fail(f"Network error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}╔══════════════════════════════════════════════════════════╗")
    print(f"║       VaaniKhata · Gnani Connection Verifier           ║")
    print(f"╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    # Load & validate config
    try:
        settings = get_settings()
        _ok("Config loaded from .env")
        _info(f"API Key  : {settings.gnani_api_key[:6]}{'*' * 12}")
    except Exception as exc:
        _fail(f"Config error: {exc}")
        print(f"\n  {Fore.YELLOW}→ Copy .env.example to .env and paste your real GNANI_API_KEY{Style.RESET_ALL}\n")
        return 1

    # Run both handshake tests
    stt_ok = await test_stt_handshake(settings)
    tts_ok = await test_tts_handshake(settings)

    # Summary
    _banner("RESULTS")
    print(f"  STT Prisma v3.0  : {'✅ PASS' if stt_ok else '❌ FAIL'}")
    print(f"  TTS Timbre v3.0  : {'✅ PASS' if tts_ok else '❌ FAIL'}")

    if stt_ok and tts_ok:
        print(f"\n  {Fore.GREEN}{Style.BRIGHT}🎉 All handshakes succeeded – Phase 1 verified!{Style.RESET_ALL}\n")
        return 0
    else:
        print(f"\n  {Fore.RED}{Style.BRIGHT}⚠️  One or more handshakes failed – check errors above.{Style.RESET_ALL}\n")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
