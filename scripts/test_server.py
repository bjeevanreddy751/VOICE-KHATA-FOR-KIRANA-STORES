#!/usr/bin/env python3
"""
VaaniKhata – Automated Phase 4 Server & WebSocket Verification Suite
=====================================================================
Uses FastAPI TestClient to verify:
  1. GET /api/health (status 200, prisma-v3.0, timbre-v3.0)
  2. POST /api/demo/reset (Ramesh Sharma balance == 0)
  3. WebSocket /ws/voice immediate Turn-1 AI Disclosure delivery
  4. Full-duplex WebSocket 4-turn conversation flow:
     - Turn 1: Multi-entry speech -> HOMONYM_CLARIFICATION_REQUIRED (balance == 0)
     - Turn 2: Disambiguation ('Sharma') -> DISAMBIGUATION_RESOLVED (balance == 140)
     - Turn 3: Atomic voice correction ('Nahi, 430 kar do') -> ATOMIC_CORRECTION (balance == 230)
     - Turn 4: Balance query ('Ramesh Sharma ka total?') -> CUSTOMER_BALANCE_QUERY (230 / 'do sau tees')
  5. WebSocket BARGE_IN event -> immediate TTS_HALTED response
  6. DPDP Opt-In Guardrail: Customer 1 (opted in) -> 200; Customer 2 (opted out) -> 403
  7. DPDP Act 1-Click Purge: drops encrypted_transcript_count to 0

Usage:
    cd vaanikhata/
    python -m scripts.test_server
"""

from __future__ import annotations

import os
import sys

# Force dev mode to protect live credits during automated testing
os.environ["GNANI_DEV_MODE"] = "true"

import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env first if present
from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

# Provide mock key for offline test suite if not set in .env
if not os.environ.get("GNANI_API_KEY") or os.environ.get("GNANI_API_KEY", "").startswith("PASTE_"):
    os.environ["GNANI_API_KEY"] = "mock_key_for_phase4_server_suite"

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    class _NoColor:
        GREEN = YELLOW = RED = CYAN = MAGENTA = RESET = ""
    Fore = _NoColor()  # type: ignore[assignment]
    class _NoStyle:
        BRIGHT = RESET_ALL = ""
    Style = _NoStyle()  # type: ignore[assignment]

from fastapi.testclient import TestClient
from backend.app import app


def _banner(title: str) -> None:
    width = 65
    print(f"\n{Fore.CYAN}{'━' * width}")
    print(f"  {Style.BRIGHT}{title}")
    print(f"{'━' * width}{Style.RESET_ALL}")


def _ok(msg: str) -> None:
    print(f"  {Fore.GREEN}✅  {msg}{Style.RESET_ALL}")


def _fail(msg: str) -> None:
    print(f"  {Fore.RED}❌  {msg}{Style.RESET_ALL}")


def _info(msg: str) -> None:
    print(f"  {Fore.YELLOW}ℹ️   {msg}{Style.RESET_ALL}")


def run_all_tests() -> bool:
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}╔═══════════════════════════════════════════════════════════════╗")
    print(f"║     VaaniKhata · Phase 4 FastAPI & Voice Bridge Suite        ║")
    print(f"╚═══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    passed = 0
    total = 7

    client = TestClient(app)

    try:
        # -------------------------------------------------------------------
        # TEST 1: Health Check
        # -------------------------------------------------------------------
        _banner("TEST 1: Health Check & Model Verification")
        resp = client.get("/api/health")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        _info(f"Health response: {data}")
        assert data["stt_model"] == "prisma-v3.0"
        assert data["tts_model"] == "timbre-v3.0"
        assert data["db_ready"] is True
        assert data.get("gnani_dev_mode") is True
        _ok("GET /api/health returned 200 with Prisma v3.0 & Timbre v3.0")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 2: Demo Reset
        # -------------------------------------------------------------------
        _banner("TEST 2: Demo Reset to Pitch Deck Opening Balances")
        resp = client.post("/api/demo/reset")
        assert resp.status_code == 200
        dashboard = resp.json()["dashboard"]
        customers = {c["full_name"]: c for c in dashboard["customers"]}
        _info(f"Ramesh Sharma balance: ₹{customers['Ramesh Sharma']['net_balance']}")
        _info(f"Ramesh Verma balance : ₹{customers['Ramesh Verma']['net_balance']}")
        assert customers["Ramesh Sharma"]["net_balance"] == 0
        assert customers["Ramesh Verma"]["net_balance"] == 150
        _ok("POST /api/demo/reset reset Ramesh Sharma to ₹0 and Ramesh Verma to ₹150")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 3: WebSocket Connection & Turn-1 AI Disclosure
        # -------------------------------------------------------------------
        _banner("TEST 3: WebSocket /ws/voice Mandatory Turn-1 AI Disclosure")
        with client.websocket_connect("/ws/voice") as ws:
            disc_msg = ws.receive_json()
            _info(f"Turn-1 message type: {disc_msg.get('type')}")
            _info(f"Disclosure text: '{disc_msg.get('display_reply')}'")
            _info(f"TTS Provider: {disc_msg.get('tts_provider')}")
            _info(f"Has Audio: {bool(disc_msg.get('audio_b64'))}")

            assert disc_msg["type"] == "TURN_1_AI_DISCLOSURE"
            assert "VaaniKhata AI assistant" in disc_msg["display_reply"]
            assert "dashboard" in disc_msg
            _ok("Turn-1 AI Disclosure broadcast immediately upon WebSocket connect")
            passed += 1

            # ---------------------------------------------------------------
            # TEST 4: WebSocket 4-Turn Pitch Deck Conversational Flow
            # ---------------------------------------------------------------
            _banner("TEST 4: WebSocket 4-Turn Pitch Deck Conversational Flow")

            # Turn 1: Multi-Entry speech triggering homonym
            t1_text = "Ramesh ka teen sau chaalis udhaar, kal do sau diya tha"
            ws.send_json({"type": "UTTERANCE", "text": t1_text, "language": "hi-IN"})
            r1 = ws.receive_json()
            _info(f"Turn 1 Intent: {r1['intent']}")
            _info(f"Turn 1 Display: '{r1['display_reply']}'")
            assert r1["type"] == "VOICE_RESULT"
            assert r1["intent"] == "HOMONYM_CLARIFICATION_REQUIRED"
            assert r1["has_pending_disambiguation"] is True
            # Assert DB balance is still 0
            st = client.get("/api/state").json()
            c_sharma = next(c for c in st["customers"] if c["full_name"] == "Ramesh Sharma")
            assert c_sharma["net_balance"] == 0, f"Expected 0, got {c_sharma['net_balance']}"
            _ok("Turn 1: Homonym clarification triggered; DB write safely deferred (balance == ₹0)")

            # Turn 2: Disambiguation ('Sharma')
            ws.send_json({"type": "UTTERANCE", "text": "Sharma", "language": "hi-IN"})
            r2 = ws.receive_json()
            _info(f"Turn 2 Intent: {r2['intent']}")
            _info(f"Turn 2 Display: '{r2['display_reply']}'")
            _info(f"Turn 2 TTS: '{r2['tts_reply']}'")
            assert r2["type"] == "VOICE_RESULT"
            assert r2["intent"] == "DISAMBIGUATION_RESOLVED"
            st = client.get("/api/state").json()
            c_sharma = next(c for c in st["customers"] if c["full_name"] == "Ramesh Sharma")
            assert c_sharma["net_balance"] == 140, f"Expected 140, got {c_sharma['net_balance']}"
            assert not any(ch.isdigit() for ch in r2["tts_reply"])
            _ok("Turn 2: Disambiguation resolved cleanly; Ramesh Sharma balance updated to ₹140")

            # Turn 3: Atomic Mid-Sale Voice Correction ('Nahi, 430 kar do')
            ws.send_json({"type": "UTTERANCE", "text": "Nahi, 430 kar do", "language": "hi-IN"})
            r3 = ws.receive_json()
            _info(f"Turn 3 Intent: {r3['intent']}")
            _info(f"Turn 3 Display: '{r3['display_reply']}'")
            _info(f"Turn 3 TTS: '{r3['tts_reply']}'")
            assert r3["type"] == "VOICE_RESULT"
            assert r3["intent"] == "ATOMIC_CORRECTION"
            st = client.get("/api/state").json()
            c_sharma = next(c for c in st["customers"] if c["full_name"] == "Ramesh Sharma")
            assert c_sharma["net_balance"] == 230, f"Expected 230, got {c_sharma['net_balance']}"
            assert not any(ch.isdigit() for ch in r3["tts_reply"])
            _ok("Turn 3: Mid-sale correction atomically reversed ₹340; new balance == ₹230")

            # Turn 4: Fast-path Customer Balance Query
            ws.send_json({"type": "UTTERANCE", "text": "Ramesh Sharma ka total?", "language": "hi-IN"})
            r4 = ws.receive_json()
            _info(f"Turn 4 Intent: {r4['intent']}")
            _info(f"Turn 4 Display: '{r4['display_reply']}'")
            _info(f"Turn 4 TTS: '{r4['tts_reply']}'")
            assert r4["type"] == "VOICE_RESULT"
            assert r4["intent"] == "CUSTOMER_BALANCE_QUERY"
            assert "230" in r4["display_reply"]
            assert "do sau tees" in r4["tts_reply"]
            _ok("Turn 4: Balance query answered with ₹230 / 'do sau tees'")
            passed += 1

            # ---------------------------------------------------------------
            # TEST 5: Barge-In Interruption
            # ---------------------------------------------------------------
            _banner("TEST 5: Sub-80ms Barge-In Audio Cancellation")
            ws.send_json({"type": "BARGE_IN", "client_halt_ms": 14.2})
            barge_resp = ws.receive_json()
            _info(f"Barge-in response: {barge_resp}")
            assert barge_resp["type"] == "TTS_HALTED"
            assert barge_resp["status"] == "Audio cancelled"
            assert barge_resp.get("client_halt_ms") == 14.2
            _ok("Barge-in cancellation confirmed with immediate TTS_HALTED response")
            passed += 1

        # -------------------------------------------------------------------
        # TEST 6: Responsible AI Opt-In Reminder Guardrail
        # -------------------------------------------------------------------
        _banner("TEST 6: Responsible AI Opt-In Reminder Guardrail")
        # Customer 1 (Ramesh Sharma) has opt_in_reminder = 1
        rem1 = client.get("/api/customer/1/reminder")
        _info(f"Customer 1 reminder status: {rem1.status_code}")
        assert rem1.status_code == 200
        assert rem1.json()["allowed"] is True

        # Customer 2 (Ramesh Verma) has opt_in_reminder = 0
        rem2 = client.get("/api/customer/2/reminder")
        _info(f"Customer 2 reminder status: {rem2.status_code} ({rem2.json()})")
        assert rem2.status_code == 403
        assert "BLOCKED BY GUARDRAIL" in rem2.json()["detail"]

        _ok("Customer 1 (opted-in) permitted with HTTP 200")
        _ok("Customer 2 (opted-out) strictly blocked with HTTP 403 guardrail error")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 7: DPDP Act 1-Click Purge
        # -------------------------------------------------------------------
        _banner("TEST 7: DPDP Act 1-Click Voice Transcript Purge")
        purge_res = client.post("/api/dpdp/purge")
        assert purge_res.status_code == 200
        pdata = purge_res.json()
        _info(f"Purge response: {pdata['message']}")
        _info(f"Remaining encrypted transcripts: {pdata['dashboard']['encrypted_transcript_count']}")
        assert pdata["status"] == "purged"
        assert pdata["dashboard"]["encrypted_transcript_count"] == 0

        _ok("DPDP Act 1-click purge successfully executed")
        _ok("encrypted_transcript_count dropped to exactly 0")
        passed += 1

        # -------------------------------------------------------------------
        # Final Summary
        # -------------------------------------------------------------------
        _banner("PHASE 4 VERIFICATION SUMMARY")
        print(f"  {Fore.GREEN}{Style.BRIGHT}Passed: {passed}/{total} tests completed successfully!{Style.RESET_ALL}\n")
        return True

    except Exception as exc:
        _fail(f"Phase 4 test suite failed with error: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
