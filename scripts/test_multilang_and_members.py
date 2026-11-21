#!/usr/bin/env python3
"""
VaaniKhata – Multi-Regional Auto-Detection & Member Management Verification Suite
==================================================================================
Tests:
  1. REST Customer Creation (`POST /api/customers`):
     - Adds 'Kiran Kumar' (Koramangala) with opening balance ₹100.
     - Verifies HTTP 201, ACID transaction history, and dashboard presence.
  2. Voice Add-Member Command:
     - 'Naya grahak Manoj Gupta Indiranagar khata kholo' -> CUSTOMER_CREATED
  3. Regional Indic Language Auto-Detection & Localized Spoken Replies:
     - Kannada : 'Suresh ge 100 saala, ninne 50 kotta' -> kn-IN
     - Tamil   : 'Suresh kadan 100, nethu 50 kodutha'  -> ta-IN
     - Telugu  : 'Suresh appu 100, ninna 50 ichadu'   -> te-IN
     - Marathi : 'Suresh chi 100 udhaari'             -> mr-IN
     - English : 'Suresh balance total'               -> en-IN
  4. WebSocket Regional Configuration (`SET_LANGUAGE`):
     - Sets language to Kannada, Tamil, etc., returning localized Turn-1 disclosures.
  5. REST Customer Deletion (`DELETE /api/customers/{id}`):
     - Deletes 'Kiran Kumar' & 'Manoj Gupta' cleanly with ACID cascade.

Usage:
    cd vaanikhata/
    python -m scripts.test_multilang_and_members
"""

from __future__ import annotations

import os
import sys

# Force dev mode to protect live credits during testing
os.environ["GNANI_DEV_MODE"] = "true"

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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
from backend import database


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
    print(f"║   VaaniKhata · Multilingual & Member Management Test Suite    ║")
    print(f"╚═══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    passed = 0
    total = 5

    client = TestClient(app)

    try:
        # Reset DB first
        client.post("/api/demo/reset")

        # -------------------------------------------------------------------
        # TEST 1: REST Customer Creation (POST /api/customers)
        # -------------------------------------------------------------------
        _banner("TEST 1: REST Customer Creation with Opening Balance")
        payload = {
            "first_name": "Kiran",
            "last_name": "Kumar",
            "landmark": "Koramangala",
            "phone": "+91-9845011199",
            "opt_in_reminder": True,
            "opening_balance": 100,
        }
        res = client.post("/api/customers", json=payload)
        assert res.status_code == 201, f"Expected 201, got {res.status_code}"
        body = res.json()
        cust = body["customer"]
        _info(f"Created customer: {cust['full_name']} (ID: {cust['id']}), Balance: ₹{cust['net_balance']}")
        assert cust["full_name"] == "Kiran Kumar"
        assert cust["landmark"] == "Koramangala"
        assert cust["net_balance"] == 100

        kiran_id = cust["id"]

        # Check in dashboard
        dash = client.get("/api/state").json()
        found = any(c["id"] == kiran_id for c in dash["customers"])
        assert found, "Kiran Kumar not found in dashboard customers list"
        _ok("POST /api/customers created 'Kiran Kumar' with opening balance ₹100")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 2: Voice Add-Member Utterance
        # -------------------------------------------------------------------
        _banner("TEST 2: Voice Add-Member Intent")
        voice_res = client.post(
            "/api/voice-turn",
            json={"text": "Naya grahak Manoj Gupta landmark Indiranagar khata kholo", "language": "hi-IN"},
        )
        assert voice_res.status_code == 200
        vdata = voice_res.json()
        _info(f"Intent: {vdata['intent']}")
        _info(f"Display Reply: '{vdata['display_reply']}'")
        assert vdata["intent"] == "CUSTOMER_CREATED"
        assert "Manoj Gupta" in vdata["display_reply"]

        # Verify Manoj Gupta is in database
        lookup = database.find_customers_by_name("Manoj Gupta")
        assert len(lookup) == 1
        manoj_id = lookup[0]["id"]
        _ok("Voice command 'Naya grahak Manoj Gupta...' parsed as CUSTOMER_CREATED and saved to DB")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 3: Multi-Regional Indic Language Auto-Detection
        # -------------------------------------------------------------------
        _banner("TEST 3: Multi-Regional Indic Auto-Detection & Replies")

        test_cases = [
            {
                "lang_name": "Kannada",
                "text": "Suresh ge 100 saala, ninne 50 kotta",
                "expected_lang": "kn-IN",
                "contains_word": "noor",  # 'mooru noora moovattu'
            },
            {
                "lang_name": "Tamil",
                "text": "Suresh kadan 100, nethu 50 kodutha",
                "expected_lang": "ta-IN",
                "contains_word": "munnoothi",  # 300 in Tamil
            },
            {
                "lang_name": "Telugu",
                "text": "Suresh appu 100, ninna 50 ichadu",
                "expected_lang": "te-IN",
                "contains_word": "vanda",  # 'moodu vandala'
            },
            {
                "lang_name": "Marathi",
                "text": "Suresh chi 100 udhaari",
                "expected_lang": "mr-IN",
                "contains_word": "shambhar",  # 100 in Marathi
            },
            {
                "lang_name": "English",
                "text": "Suresh balance total",
                "expected_lang": "en-IN",
                "contains_word": "rupees",
            },
        ]

        with client.websocket_connect("/ws/voice") as ws:
            # Drain Turn 1 disclosure
            ws.receive_json()

            for tc in test_cases:
                ws.send_json({"type": "UTTERANCE", "text": tc["text"]})
                reply = ws.receive_json()
                detected = reply.get("detected_language")
                tts_text = reply.get("tts_reply", "")
                _info(f"[{tc['lang_name']}] Input: '{tc['text']}' -> Detected: {detected}")
                _info(f"[{tc['lang_name']}] TTS reply: '{tts_text}'")

                assert detected == tc["expected_lang"], (
                    f"Expected {tc['expected_lang']}, got {detected} for input '{tc['text']}'"
                )
                # Ensure strictly zero raw digits in TTS spoken words
                assert not any(ch.isdigit() for ch in tts_text), (
                    f"TTS reply contains raw digits: '{tts_text}'"
                )
                assert tc["contains_word"] in tts_text.lower(), (
                    f"Expected '{tc['contains_word']}' in TTS reply: '{tts_text}'"
                )
                _ok(f"Language {tc['lang_name']} ({tc['expected_lang']}) detected & localized correctly")

        passed += 1

        # -------------------------------------------------------------------
        # TEST 4: WebSocket SET_LANGUAGE Command
        # -------------------------------------------------------------------
        _banner("TEST 4: WebSocket SET_LANGUAGE Dynamic Switch")
        with client.websocket_connect("/ws/voice") as ws:
            ws.receive_json()  # Turn 1 disclosure

            for target_lang in ["kn-IN", "ta-IN", "te-IN", "mr-IN", "en-IN", "hi-IN"]:
                ws.send_json({"type": "SET_LANGUAGE", "language": target_lang})
                res = ws.receive_json()
                assert res["type"] == "LANGUAGE_UPDATED"
                assert res["language"] == target_lang
                assert not any(ch.isdigit() for ch in res.get("tts_reply", ""))
                _info(f"Switched to {target_lang}: '{res['display_reply'][:50]}...'")

            _ok("WebSocket SET_LANGUAGE successfully updated session across all Indic languages")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 5: REST Customer Deletion (DELETE /api/customers/{id})
        # -------------------------------------------------------------------
        _banner("TEST 5: REST Customer Deletion (Cleanup)")
        del1 = client.delete(f"/api/customers/{kiran_id}")
        assert del1.status_code == 200
        assert del1.json()["deleted"] is True

        del2 = client.delete(f"/api/customers/{manoj_id}")
        assert del2.status_code == 200
        assert del2.json()["deleted"] is True

        # Verify non-existent ID returns 404
        del3 = client.delete("/api/customers/99999")
        assert del3.status_code == 404
        _ok("DELETE /api/customers successfully deleted created members and returned 404 on invalid ID")
        passed += 1

        # -------------------------------------------------------------------
        # Final Summary
        # -------------------------------------------------------------------
        _banner("MULTILINGUAL & MEMBER VERIFICATION SUMMARY")
        print(f"  {Fore.GREEN}{Style.BRIGHT}Passed: {passed}/{total} tests completed successfully!{Style.RESET_ALL}\n")
        return True

    except Exception as exc:
        _fail(f"Multilingual test suite failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
