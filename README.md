# VaaniKhata (वाणीखाता) · Voice Khata for Kirana Stores
> **Gnani Voice Hackathon · Track PS2**  
> *Speak. Record. Settle. — Multilingual Voice AI Bookkeeping with Zero LLM Arithmetic.*

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Gnani Prisma](https://img.shields.io/badge/Gnani-Prisma%20v3.0%20STT-orange)](https://vachana.ai)
[![Gnani Timbre](https://img.shields.io/badge/Gnani-Timbre%20v3.0%20TTS-blue)](https://vachana.ai)
[![SQLite ACID](https://img.shields.io/badge/Database-SQLite%20WAL%20ACID-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)
[![DPDP Act](https://img.shields.io/badge/Security-AES--256%20DPDP%20Compliant-success)](#dpdp-act-2023-compliance)
[![Tests](https://img.shields.io/badge/Tests-27%2F27%20Passing-brightgreen)](#automated-test-verification)

---

## 📌 Executive Summary
Small retail kirana stores in India operate under razor-thin margins with high friction in credit bookkeeping (*udhaar* / *jama*). Physical paper diaries (*bahi-khata*) lead to forgotten balances, delayed collections, and strained customer relationships. While smartphone ledger apps exist, typing numbers and navigating nested touch menus while packing groceries is disruptive.

**VaaniKhata** provides a full-duplex, real-time voice ledger powered by **Gnani Prisma v3.0 STT** and **Gnani Timbre v3.0 TTS**:
- **Zero LLM Arithmetic:** 100% of ledger balances, credits, and debits are evaluated deterministically in SQLite with ACID transactions and Write-Ahead Logging (WAL). LLMs never touch financial math.
- **Sub-80ms Barge-In Interruption:** Shopkeepers can interrupt the voice assistant at any millisecond to correct amounts (*"Nahi, 430 kar do"* atomically reverses the previous transaction and posts the corrected amount).
- **Sub-5ms Indic Numeral Normalizer:** Deterministic zero-dependency normalizer handling code-mixed Hindi, Kannada, Tamil, Telugu, Marathi, Hinglish, and colloquial English numerals (*"dedh sau"*, *"dhai sau"*, *"three-forty"*, *"eradu nooru"*).
- **Zero Raw Digits in Speech Synthesis:** Every number is converted into natural spoken words before synthesis so Gnani Timbre v3.0 never mispronounces currency or reads digits robotically.
- **Responsible Voice AI & DPDP Act (India) Compliance:** Turn-1 AI Disclosure baseline, AES-256 Fernet field-level encryption at rest, 1-click voice transcript purge, and opt-in enforcement blocking unsolicited debt collection messages.

---

## 🏛️ System Architecture

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
[ Indic Numeral Parser ]                 │
(backend/numeral_parser.py)              │
│                                        │
▼ (Normalized amounts & relative dates)  │
[ Stateful Ledger Engine ] ──────────────┘
(backend/ledger_engine.py)
│
▼ (ACID Writes & Atomic Reversals)
[ AES-256 Encrypted SQLite Ledger ]
 (backend/database.py - WAL Mode)
```

---

## 🚀 Key Features

### 1. Multi-Regional Language Engine (6 Indic Languages)
Seamlessly switch or auto-detect speech across:
- **हिन्दी (Hindi - `hi-IN`)**
- **ಕನ್ನಡ (Kannada - `kn-IN`)**
- **தமிழ் (Tamil - `ta-IN`)**
- **తెలుగు (Telugu - `te-IN`)**
- **मराठी (Marathi - `mr-IN`)**
- **English (`en-IN`)**

### 2. Atomic Mid-Sale Voice Correction
If a shopkeeper says *"Ramesh ka 340 udhaar"* and immediately follows with *"Nahi, 430 kar do"*:
1. The engine marks transaction #1 as `REVERSED` in SQLite.
2. It atomically inserts transaction #2 for ₹430 linked via `replaces_tx_id`.
3. The net customer balance updates deterministically from ₹140 to ₹230 without manual typing.

### 3. Homonym Disambiguation
When multiple customers share the same first name (e.g. *Ramesh Sharma* on MG Road vs. *Ramesh Verma* on Brigade Road), the engine defers database writes and prompts:
> *"Do Ramesh hain — Ramesh Sharma (MG Road) ya Ramesh Verma (Brigade Road)? Kiske khaate mein likhoon?"*
Spoken clarification immediately completes the atomic write.

### 4. Scannable UPI Settlement QR Code
For opted-in customers with pending balances, generating a payment reminder displays an instant scannable UPI QR code (`upi://pay?pa=vaanikhata@upi&pn=VaaniKhata+Kirana&am=<balance>&cu=INR`) for Google Pay, PhonePe, Paytm, or BHIM, plus direct one-tap links to WhatsApp and SMS.

### 5. Ambient 75 dB Shop Noise Simulator
Built-in Web Audio pink/brownian noise generator allows testing Voice Activity Detection (VAD) and Barge-In in loud market environments directly on a laptop.

### 6. DPDP Act 2023 Compliance
- Plaintext voice transcripts and shop notes are never stored in plaintext on disk; all sensitive fields use AES-256 Fernet ciphers.
- **1-Click Purge:** Permanently drops all encrypted demo voice session transcripts.
- **Reminder Opt-In Guardrail:** Unsolicited reminders for opted-out customers are strictly blocked with HTTP 403.

---

## 🛠️ Tech Stack
- **Backend:** Python 3.11+, FastAPI, Uvicorn, WebSockets
- **Speech AI:** Gnani Prisma v3.0 (Streaming STT), Gnani Timbre v3.0 (Streaming TTS)
- **Database:** SQLite 3 with Write-Ahead Logging (`PRAGMA journal_mode=WAL`)
- **Cryptography:** Cryptography (`Fernet` AES-256)
- **Frontend:** Single-file installable PWA (HTML5, Tailwind CSS, Web Audio API AudioWorklet, Playfair Display)

---

## 🏁 Quick Start

### 1. Clone & Setup Virtual Environment
```bash
git clone <YOUR_GITHUB_REPO_URL>
cd vaanikhata

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy the example environment file:
```bash
cp .env.example .env
```
Edit `.env` and set your credentials:
```ini
GNANI_API_KEY=your_gnani_api_key_here
GNANI_DEV_MODE=false
```

### 3. Run the Server
```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```
Open **`http://localhost:8000`** in Google Chrome.

---

## 🧪 Automated Test Verification

VaaniKhata includes an end-to-end verification suite with **27/27 passing automated tests**:

```bash
# 1. Database & DPDP Act Verification (7 tests)
python -m scripts.test_database

# 2. Stateful Ledger & Indic Numeral Parser Matrix (8 tests, 4.38 ms avg latency)
python -m scripts.test_ledger_engine

# 3. Full-Duplex WebSocket & REST Integration (7 tests)
python -m scripts.test_server

# 4. Multi-Regional Indic & Member Management (5 tests)
python -m scripts.test_multilang_and_members
```

Run all 4 suites back-to-back:
```bash
python -m scripts.test_database; python -m scripts.test_ledger_engine; python -m scripts.test_server; python -m scripts.test_multilang_and_members
```

---

## 📂 Project Structure

```
vaanikhata/
├── backend/
│   ├── app.py                # FastAPI WebSocket voice orchestrator & REST API
│   ├── config.py             # Pydantic Settings & environment loader
│   ├── database.py           # SQLite ACID ledger with AES-256 Fernet encryption
│   ├── gnani_service.py      # Gnani Prisma v3.0 STT & Timbre v3.0 TTS clients
│   ├── ledger_engine.py      # Stateful conversational engine & session state machine
│   └── numeral_parser.py     # Sub-5ms Indic numeral & relative date normalizer
├── frontend/
│   ├── audio-processor.js    # AudioWorklet downsampler (16 kHz 16-bit mono PCM)
│   ├── index.html            # Mobile-first Kirana PWA (Light/Dark mode, UPI QR)
│   └── manifest.json         # PWA Android install manifest
├── scripts/
│   ├── test_database.py      # ACID math, seed data, and DPDP purge tests
│   ├── test_gnani_connection.py # Live WebSocket handshake diagnostic
│   ├── test_ledger_engine.py # Sub-25ms benchmark and 4-turn pitch deck flow
│   ├── test_multilang_and_members.py # 6 Indic languages & customer CRUD
│   └── test_server.py        # Full-duplex WebSocket and REST verification
├── .env.example              # Sanitized configuration template
├── .gitignore                # Excludes secrets, databases, and caches
└── requirements.txt          # Python dependencies
```

---

## 📜 License
Developed for the **Gnani Voice Hackathon 2026 (Track PS2: Voice Khata for Kirana Stores)**.
All rights reserved.
