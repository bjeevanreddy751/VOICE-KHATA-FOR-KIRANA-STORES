# VaaniKhata System Architecture Specification
======================================================
**Project:** VaaniKhata (Voice Khata for Kirana Stores)  
**Track:** PS2 (Gnani Voice Hackathon)  
**Authors:** Senior Voice AI & Backend Systems Engineering Team  
**Date:** 2026-11-21  
**Status:** Approved & Implemented (Phases 1–5 Complete)

---

## 1. Executive Summary & Problem Space
Small retail kirana stores in India operate under razor-thin margins with high friction in credit bookkeeping (*udhaar* / *jama*). Physical paper diaries (*bahi-khata*) lead to forgotten balances, delayed collections, and strained relationships. While digital apps exist, typing numbers and selecting menus while serving customers is disruptive.

**VaaniKhata** provides an interactive, full-duplex voice ledger powered by **Gnani Prisma v3.0 STT** and **Gnani Timbre v3.0 TTS** with:
- Sub-80ms Barge-In speech cancellation
- Zero-math hallucinations (deterministic SQLite ACID arithmetic with WAL mode)
- Responsible AI Turn-1 disclosure and DPDP Act compliance (AES-256 Fernet encryption at rest, 1-click voice transcript purge, reminder opt-in guardrails)
- Robust Indic retail speech normalization (handling code-mixed Hinglish, Kannada numerals, fractions like *dedh sau*, *dhai sau*, and relative dates like *kal*, *parso*).

---

## 2. System Architecture & Component Mapping

```
                                 [ Kirana Shopkeeper ]
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   │                                             │
      [ Mobile Chrome PWA / Laptop UI ]                          │
                   │                                             │
                   │  16 kHz PCM Audio / JSON WebSocket          │
                   ▼                                             ▼
        [ FastAPI Voice Orchestrator ]                 [ Web Browser Audio ]
             (backend/app.py)                       (Autoplay Unlock + Barge-In)
                   │
    ┌──────────────┴─────────────────────────┐
    │                                        │
    ▼                                        ▼
[ Gnani Prisma v3.0 STT ]         [ Gnani Timbre v3.0 TTS ]
 (wss://api.vachana.ai/stt/...)    (wss://api.vachana.ai/api/v1/tts)
    │                                        ▲
    ▼ (Transcripts)                          │ (Zero-digit Spoken Words)
[ Indic Numeral Parser ]                     │
(backend/numeral_parser.py)                  │
    │                                        │
    ▼ (340, 430, relative dates)             │
[ Stateful Ledger Engine ] ──────────────────┘
(backend/ledger_engine.py)
    │
    ▼ (ACID Writes & Reversals)
[ AES-256 Encrypted SQLite Ledger ]
 (backend/database.py - WAL Mode)
```

---

## 3. Core Subsystems

### 3.1 Indic Numeral & Date Normalizer (`backend/numeral_parser.py`)
- Translates Devanagari (`०-९`), Kannada (`೦-೯`), and Tamil digits into standard ASCII digits.
- Evaluates compound Hindi/Hinglish numbers (*teen sau chaalis* -> `340`, *chaar sau tees* -> `430`, *ek hazaar do sau* -> `1200`), fractions (*dedh sau* -> `150`, *dhai sau* -> `250`, *saadhe teen sau* -> `350`), colloquial English retail speech (*three-forty* -> `340`), and Kannada numerals (*eradu nooru* -> `200`).
- Resolves relative temporal markers (*parso* -> `-2 days`, *kal* -> `-1 day`, *aaj* -> `today`).
- Generates clean Hindi words for TTS via `number_to_spoken_hindi()` containing strictly zero ASCII digits (`0-9`) to prevent mispronunciation.

### 3.2 Stateful Conversational Ledger Engine (`backend/ledger_engine.py`)
- Evaluates 9 deterministic intent states without sending numbers to LLMs.
- Manages session state machine (`SessionState`):
  - `pending_disambiguation`: Stored when homonyms occur (*"Ramesh"* matches Ramesh Sharma & Ramesh Verma); defers database writes until the user clarifies.
  - `last_committed_tx_id`: Enables atomic mid-sale voice corrections (*"Nahi, 430 kar do"* reverses the ₹340 row and inserts ₹430 linked via `replaces_tx_id`).
  - `last_customer_id`: Enables contextual follow-up balance queries.
- Enforces Responsible AI Guardrail (blocks loans, interest, harassment, and debt-collection threats with `GUARDRAIL_BLOCKED`).
- Fallback slot extractor with Gemini 2.5 Flash wrapped in a 1.2s timeout with zero financial math delegation.

### 3.3 Encrypted ACID Ledger (`backend/database.py`)
- SQLite database configured with `PRAGMA foreign_keys = ON;` and `PRAGMA journal_mode = WAL;`.
- Tables:
  1. `customers`: `id`, `full_name`, `landmark`, `phone`, `opt_in_reminder`, `net_balance`.
  2. `transactions`: `id`, `customer_id`, `amount`, `tx_type`, `tx_date`, `relative_label`, `status`, `replaces_tx_id`, `encrypted_raw_note`, `created_at`.
  3. `demo_transcripts`: `id`, `encrypted_transcript`, `encrypted_response`, `intent`, `latency_ms`, `created_at`.
- AES-256 Fernet encryption at rest: raw spoken text and transcripts are never stored in plaintext.
- Synthetic seed data aligned to Pitch Deck math (Opening balances: Ramesh Sharma ₹0, Ramesh Verma ₹150, Suresh Gowda ₹280, Lakshmi Devi ₹0).

### 3.4 Live Streaming Voice Bridge (`backend/gnani_service.py`)
- **Gnani Timbre v3.0 Streaming TTS:** WebSocket upgrade with `X-API-Key-ID`. Assembles streamed PCM chunks with standard 44-byte WAV headers. Caches Turn-1 AI Disclosure audio in memory for instant `<20ms` replay. Supports `<80ms` barge-in cancellation via `asyncio.Event`.
- **Gnani Prisma v3.0 Streaming STT:** Full-duplex PCM binary streamer (16 kHz, 16-bit mono, 1,024-byte frames). Supports push-to-talk commit endpointing and partial recognition feeds.

### 3.5 FastAPI Orchestrator & REST Endpoints (`backend/app.py`)
- WebSocket endpoint `/ws/voice` handling binary PCM frames, `BARGE_IN`, `START_AUDIO`, `COMMIT`, `UTTERANCE`.
- Mandatory Turn-1 AI Disclosure broadcast on initial connect.
- REST endpoints: `/api/health`, `/api/state`, `/api/voice-turn`, `/api/customer/opt-in`, `/api/customer/{id}/reminder`, `/api/dpdp/purge`, `/api/demo/reset`.

### 3.6 PWA Mobile & Desktop Frontend (`frontend/index.html`)
- Warm editorial Kirana design (Cream `#FAF6F0`, Terracotta `#C83E2B`, Sage `#2E6F40`, Charcoal `#1A1A1A`).
- Push-to-Talk button with pointer events and keyboard Spacebar hold.
- AudioContext autoplay unlock banner.
- 1-click Quick-Trigger demo chips for hackathon pitch demonstration.
- Real-time customer cards, collapsible transaction audit logs, and DPDP reminder test modal.

---

## 4. Verification & Benchmarking
- **Phase 2 (Database & Cryptography):** 7/7 tests passed.
- **Phase 3 (Numeral Parser & Ledger Engine):** 8/8 tests passed (Average deterministic engine latency: 4.34 ms).
- **Phase 4 (Server REST & WebSocket Bridge):** 7/7 tests passed with live Gnani API platform integration.
- **Phase 5 (PWA Frontend Delivery):** Clean serving of `index.html`, `manifest.json`, and `audio-processor.js`.
