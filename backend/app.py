"""
VaaniKhata – FastAPI Full-Duplex Voice Server & REST API
=========================================================
Orchestrates:
  • Full-duplex WebSocket (/ws/voice) with Gnani Timbre & Prisma
  • Sub-80ms Barge-In interruption handling
  • Turn-1 AI Disclosure baseline for Responsible Voice AI
  • ACID ledger transactions & customer homonym resolution
  • DPDP Act compliant endpoints (1-click purge, opt-in enforcement)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import database
from backend.config import get_settings
from backend.gnani_service import (
    PrismaSTTClient,
    is_gnani_configured,
    synthesize_timbre_tts,
)
from backend.ledger_engine import SessionState, get_ai_disclosure, process_utterance

logger = logging.getLogger("vaanikhata.app")

# ---------------------------------------------------------------------------
# Project Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"
_INDEX_HTML = _FRONTEND_DIR / "index.html"

# Isolated REST session states by session ID (X-Session-ID header)
_REST_SESSIONS: dict[str, SessionState] = {}


def get_rest_session(session_id: Optional[str] = None) -> SessionState:
    """
    Retrieve or initialize isolated SessionState for the given session_id.
    Guarantees two simultaneous tabs/judges never overwrite each other's state.
    """
    sid = (session_id or "default").strip()
    if not sid:
        sid = "default"
    if sid not in _REST_SESSIONS:
        _REST_SESSIONS[sid] = SessionState()
    return _REST_SESSIONS[sid]

# Mandatory Turn-1 AI Disclosure text (Responsible AI Baseline)
DISCLOSURE_TEXT = (
    "Namaste! Main VaaniKhata AI assistant hoon. "
    "Aap bolkar apne kirana store ka udhaar aur jama likh sakte hain."
)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and seed demo data on startup."""
    database.init_db()
    logger.info("VaaniKhata database initialized and ready.")
    if is_gnani_configured():
        try:
            logger.info("Pre-warming Gnani Timbre v3.0 Turn-1 AI Disclosure audio cache...")
            res = await synthesize_timbre_tts(DISCLOSURE_TEXT, language_code="hi-IN")
            if res.get("audio_b64"):
                logger.info("Turn-1 AI Disclosure audio cache warmed successfully.")
        except Exception as e:
            logger.warning(f"Could not pre-warm Timbre TTS: {e}")
    yield


# ---------------------------------------------------------------------------
# FastAPI App Setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="VaaniKhata API",
    description="Multilingual Voice Khata for Indian Kirana Stores",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend static files if directory exists
if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")


@app.get("/manifest.json")
async def get_manifest():
    """Serve PWA manifest for Android Chrome installability."""
    p = _FRONTEND_DIR / "manifest.json"
    if p.exists():
        return FileResponse(str(p), media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="manifest.json not found")


@app.get("/audio-processor.js")
async def get_audio_processor():
    """Serve Web Audio AudioWorkletProcessor script."""
    p = _FRONTEND_DIR / "audio-processor.js"
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="audio-processor.js not found")


# ---------------------------------------------------------------------------
# Root Endpoint
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    """Serve frontend PWA index.html if present; otherwise return status JSON."""
    if _INDEX_HTML.exists():
        return FileResponse(str(_INDEX_HTML))
    return JSONResponse(
        {
            "status": "online",
            "app": "VaaniKhata",
            "track": "PS2: Voice Khata for Kirana Stores",
            "message": "Backend is active. Frontend UI will be delivered in Phase 5.",
            "health_check": "/api/health",
            "ws_voice": "/ws/voice",
        }
    )


# ---------------------------------------------------------------------------
# Full-Duplex Voice WebSocket (/ws/voice)
# ---------------------------------------------------------------------------
@app.websocket("/ws/voice")
async def voice_websocket(
    ws: WebSocket,
    session_id: Optional[str] = Query(None),
    live: Optional[str] = Query(None),
):
    """
    Full-duplex WebSocket orchestrating:
      - Mandatory Turn-1 AI Disclosure (synthesized or cached)
      - Push-to-Talk PCM binary audio streaming to Gnani Prisma v3.0 STT
      - Text / WebSpeech fallback utterances
      - Real client-side Barge-In speech cancellation
      - Live stateful ledger engine processing and Timbre v3.0 TTS output
    """
    await ws.accept()

    # Query param detection (?live=1 & ?session_id=...)
    live_param = ws.query_params.get("live", live or "")
    bypass_cache = str(live_param).lower() in ("1", "true", "yes")
    ws_session_id = ws.query_params.get("session_id", session_id or "")

    session = get_rest_session(ws_session_id) if ws_session_id else SessionState()
    prisma_client: Optional[PrismaSTTClient] = None
    tts_cancel_event = asyncio.Event()

    try:
        # ── Turn-1 AI Disclosure Baseline ─────────────────────────────────
        session.ai_disclosed = True
        tts_res = await synthesize_timbre_tts(
            DISCLOSURE_TEXT,
            language_code="hi-IN",
            cancel_event=tts_cancel_event,
            bypass_cache=bypass_cache,
        )
        dashboard = database.fetch_dashboard_state()

        await ws.send_json(
            {
                "type": "TURN_1_AI_DISCLOSURE",
                "display_reply": DISCLOSURE_TEXT,
                "tts_reply": DISCLOSURE_TEXT,
                "audio_b64": tts_res.get("audio_b64"),
                "tts_provider": tts_res.get("tts_provider", "browser_fallback"),
                "tts_cached": tts_res.get("tts_cached", False),
                "dashboard": dashboard,
            }
        )

        # ── Inbound Message Loop ──────────────────────────────────────────
        while True:
            msg = await ws.receive()
            msg_type = msg.get("type")

            if msg_type == "websocket.disconnect":
                break

            # Handle Binary 16 kHz PCM chunk from client microphone
            if "bytes" in msg and msg["bytes"]:
                pcm_chunk = msg["bytes"]
                if prisma_client:
                    if prisma_client.is_timed_out():
                        logger.warning("Mic recording exceeded 12-second max guard, ignoring chunk.")
                    else:
                        await prisma_client.send_pcm_chunk(pcm_chunk)
                continue

            # Handle JSON protocol commands
            if "text" in msg and msg["text"]:
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                action = payload.get("type")

                # 0. Regional Language Configuration
                if action == "SET_LANGUAGE":
                    lang = payload.get("language", "auto")
                    session.preferred_language = lang
                    disclosure_lang = "hi-IN" if lang == "auto" else lang
                    disc_text = get_ai_disclosure(disclosure_lang)
                    tts_cancel_event = asyncio.Event()
                    tts_res = await synthesize_timbre_tts(
                        disc_text,
                        language_code=disclosure_lang,
                        cancel_event=tts_cancel_event,
                        bypass_cache=bypass_cache,
                    )
                    await ws.send_json(
                        {
                            "type": "LANGUAGE_UPDATED",
                            "language": lang,
                            "display_reply": disc_text,
                            "tts_reply": disc_text,
                            "audio_b64": tts_res.get("audio_b64"),
                            "tts_provider": tts_res.get("tts_provider", "browser_fallback"),
                            "tts_cached": tts_res.get("tts_cached", False),
                        }
                    )
                    continue

                # 1. Immediate Barge-In Cancellation
                if action == "BARGE_IN":
                    tts_cancel_event.set()
                    echoed_halt_ms = payload.get("client_halt_ms")
                    await ws.send_json(
                        {
                            "type": "TTS_HALTED",
                            "client_halt_ms": echoed_halt_ms,
                            "status": "Audio cancelled",
                        }
                    )
                    continue

                # 2. Push-to-Talk Microphone Started
                if action == "START_AUDIO":
                    tts_cancel_event.set()
                    tts_cancel_event = asyncio.Event()

                    if prisma_client:
                        await prisma_client.close()

                    if is_gnani_configured():
                        sel_lang = session.preferred_language if session.preferred_language != "auto" else "hi-IN"
                        keyterms = database.get_keyterm_roster(limit=200)
                        prisma_client = PrismaSTTClient(language=sel_lang, keywords=keyterms)
                        connected = await prisma_client.connect(keywords=keyterms)
                        stt_provider = "gnani_prisma_v3.0" if connected else "browser_fallback"
                    else:
                        prisma_client = None
                        stt_provider = "browser_fallback"

                    await ws.send_json(
                        {
                            "type": "STT_READY",
                            "stt_provider": stt_provider,
                        }
                    )
                    continue

                # 3. Push-to-Talk Microphone Released (Commit STT)
                if action == "COMMIT":
                    t0 = time.perf_counter()
                    transcript = ""
                    detected_lang = session.preferred_language if session.preferred_language != "auto" else "hi-IN"

                    if prisma_client and getattr(prisma_client, "_connected", False):
                        async def on_partial(txt: str):
                            try:
                                await ws.send_json({"type": "PARTIAL_TRANSCRIPT", "text": txt})
                            except Exception:
                                pass

                        transcript, detected_lang = await prisma_client.commit_and_get_final(on_partial)
                        await prisma_client.close()
                        prisma_client = None

                    # Resilient fallback: If Prisma returned empty or was offline, use client text
                    if not transcript and payload.get("text"):
                        transcript = payload.get("text")
                        detected_lang = payload.get("language", detected_lang)

                    # Process utterance through deterministic ledger engine
                    turn = process_utterance(transcript, session, stt_lang=detected_lang)
                    final_lang = turn.get("detected_language") or detected_lang

                    # Synthesize reply via Gnani Timbre v3.0
                    turn_bypass = bool(payload.get("bypass_cache", False)) or bypass_cache
                    tts_cancel_event = asyncio.Event()
                    tts_res = await synthesize_timbre_tts(
                        turn["tts_reply"],
                        language_code=final_lang,
                        cancel_event=tts_cancel_event,
                        bypass_cache=turn_bypass,
                    )
                    e2e_latency_ms = int((time.perf_counter() - t0) * 1000)

                    resp_payload = {
                        "type": "VOICE_RESULT",
                        "raw_transcript": turn["raw_transcript"],
                        "normalized_transcript": turn["normalized_transcript"],
                        "intent": turn["intent"],
                        "display_reply": turn["display_reply"],
                        "tts_reply": turn["tts_reply"],
                        "audio_b64": tts_res.get("audio_b64"),
                        "tts_provider": tts_res.get("tts_provider", "browser_fallback"),
                        "tts_cached": tts_res.get("tts_cached", False),
                        "engine_latency_ms": turn["engine_latency_ms"],
                        "latency_ms": e2e_latency_ms,
                        "has_pending_disambiguation": turn["has_pending_disambiguation"],
                        "detected_language": final_lang,
                        "dashboard": turn["dashboard"],
                    }
                    for k in ("highlight_customer_id", "customer", "timeline", "summary", "store_summary", "auto_enrolled"):
                        if k in turn:
                            resp_payload[k] = turn[k]

                    await ws.send_json(resp_payload)
                    continue

                # 4. Fast Text / Preset / WebSpeech Utterance
                if action == "UTTERANCE":
                    t0 = time.perf_counter()
                    tts_cancel_event.set()
                    tts_cancel_event = asyncio.Event()

                    raw_text = payload.get("text", "")
                    req_lang = payload.get("language")
                    turn_lang = session.preferred_language if session.preferred_language != "auto" else req_lang
                    turn = process_utterance(raw_text, session, stt_lang=turn_lang)
                    final_lang = turn.get("detected_language") or (
                        session.preferred_language
                        if session.preferred_language != "auto"
                        else (req_lang or "hi-IN")
                    )

                    turn_bypass = bool(payload.get("bypass_cache", False)) or bypass_cache
                    tts_res = await synthesize_timbre_tts(
                        turn["tts_reply"],
                        language_code=final_lang,
                        cancel_event=tts_cancel_event,
                        bypass_cache=turn_bypass,
                    )
                    e2e_latency_ms = int((time.perf_counter() - t0) * 1000)

                    resp_payload = {
                        "type": "VOICE_RESULT",
                        "raw_transcript": turn["raw_transcript"],
                        "normalized_transcript": turn["normalized_transcript"],
                        "intent": turn["intent"],
                        "display_reply": turn["display_reply"],
                        "tts_reply": turn["tts_reply"],
                        "audio_b64": tts_res.get("audio_b64"),
                        "tts_provider": tts_res.get("tts_provider", "browser_fallback"),
                        "tts_cached": tts_res.get("tts_cached", False),
                        "engine_latency_ms": turn["engine_latency_ms"],
                        "latency_ms": e2e_latency_ms,
                        "has_pending_disambiguation": turn["has_pending_disambiguation"],
                        "detected_language": final_lang,
                        "dashboard": turn["dashboard"],
                    }
                    for k in ("highlight_customer_id", "customer", "timeline", "summary", "store_summary", "auto_enrolled"):
                        if k in turn:
                            resp_payload[k] = turn[k]

                    await ws.send_json(resp_payload)
                    continue

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected cleanly.")
    except Exception as exc:
        logger.warning(f"Voice WebSocket session error: {exc}")
    finally:
        if prisma_client:
            await prisma_client.close()


# ---------------------------------------------------------------------------
# REST API Schemas
# ---------------------------------------------------------------------------
class VoiceTurnRequest(BaseModel):
    text: str
    language: str = "hi-IN"
    bypass_cache: bool = False


class OptInRequest(BaseModel):
    customer_id: int
    opt_in: bool


class CustomerCreateRequest(BaseModel):
    first_name: str
    last_name: str
    landmark: str
    phone: str
    opt_in_reminder: bool = True
    opening_balance: int = 0


# ---------------------------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    """System health check and live Gnani configuration status."""
    settings = get_settings()
    return {
        "status": "ok",
        "gnani_configured": is_gnani_configured(),
        "gnani_dev_mode": getattr(settings, "gnani_dev_mode", False),
        "stt_model": "prisma-v3.0",
        "tts_model": "timbre-v3.0",
        "db_ready": True,
    }


@app.get("/api/state")
async def get_state():
    """Return live dashboard state (all customers, recent tx, today's summary)."""
    return database.fetch_dashboard_state()


@app.post("/api/customers", status_code=201)
async def create_customer(req: CustomerCreateRequest):
    """Add a new kirana customer with optional opening balance (ACID transaction)."""
    try:
        cust = database.create_customer(
            first_name=req.first_name,
            last_name=req.last_name,
            landmark=req.landmark,
            phone=req.phone,
            opt_in_reminder=req.opt_in_reminder,
            opening_balance=req.opening_balance,
        )
        return {
            "customer": cust,
            "dashboard": database.fetch_dashboard_state(),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/customers/{customer_id}")
async def delete_customer(customer_id: int):
    """Safely remove a customer and their transaction history."""
    try:
        deleted = database.delete_customer(customer_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Customer not found")
        return {
            "deleted": True,
            "customer_id": customer_id,
            "dashboard": database.fetch_dashboard_state(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/voice-turn")
async def voice_turn(
    req: VoiceTurnRequest,
    live: Optional[str] = None,
    bypass_cache: Optional[bool] = None,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """Run a single conversational turn via REST and return result + TTS audio."""
    session = get_rest_session(x_session_id)
    live_param = str(live or "").strip().lower()
    is_bypass = bool(req.bypass_cache or bypass_cache or (live_param in ("1", "true", "yes")))
    t0 = time.perf_counter()
    turn = process_utterance(req.text, session, stt_lang=req.language)
    active_lang = turn.get("detected_language") or req.language
    tts_res = await synthesize_timbre_tts(turn["tts_reply"], language_code=active_lang, bypass_cache=is_bypass)
    e2e_latency = int((time.perf_counter() - t0) * 1000)

    ret = {
        "raw_transcript": turn["raw_transcript"],
        "normalized_transcript": turn["normalized_transcript"],
        "intent": turn["intent"],
        "display_reply": turn["display_reply"],
        "tts_reply": turn["tts_reply"],
        "audio_b64": tts_res.get("audio_b64"),
        "tts_provider": tts_res.get("tts_provider", "browser_fallback"),
        "tts_cached": tts_res.get("tts_cached", False),
        "engine_latency_ms": turn["engine_latency_ms"],
        "latency_ms": e2e_latency,
        "has_pending_disambiguation": turn["has_pending_disambiguation"],
        "detected_language": active_lang,
        "dashboard": turn["dashboard"],
    }
    for k in ("highlight_customer_id", "customer", "timeline", "summary", "store_summary", "auto_enrolled"):
        if k in turn:
            ret[k] = turn[k]
    return ret


@app.post("/api/customer/opt-in")
async def set_opt_in(req: OptInRequest):
    """Update customer reminder opt-in status (DPDP compliance)."""
    try:
        database.set_customer_opt_in(req.customer_id, req.opt_in)
        return {
            "status": "updated",
            "customer_id": req.customer_id,
            "opt_in": req.opt_in,
            "dashboard": database.fetch_dashboard_state(),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/customer/{customer_id}/reminder")
async def get_reminder(customer_id: int):
    """
    Fetch polite, zero-pressure reminder.
    Guaranteed HTTP 403 block if customer has not opted in.
    """
    try:
        res = database.build_polite_reminder(customer_id)
        if not res.get("allowed"):
            raise HTTPException(status_code=403, detail=res.get("reason"))
        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/dpdp/purge")
async def purge_logs():
    """DPDP Act 1-click purge: permanently wipe all encrypted voice session transcripts."""
    deleted_count = database.purge_demo_transcripts()
    return {
        "status": "purged",
        "deleted_count": deleted_count,
        "message": f"Successfully purged {deleted_count} voice transcript records under DPDP Act.",
        "dashboard": database.fetch_dashboard_state(),
    }


@app.post("/api/demo/reset")
async def reset_demo(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """Wipe and re-seed database with synthetic data for live judge demonstration."""
    sid = (x_session_id or "default").strip()
    if sid and sid != "default":
        _REST_SESSIONS[sid] = SessionState()
    else:
        _REST_SESSIONS.clear()
        _REST_SESSIONS["default"] = SessionState()
    database.reset_demo_db()
    return {
        "status": "reset",
        "message": "Demo database reset to initial pitch deck state.",
        "dashboard": database.fetch_dashboard_state(),
    }
