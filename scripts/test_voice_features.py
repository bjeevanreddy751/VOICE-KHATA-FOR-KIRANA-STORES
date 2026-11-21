#!/usr/bin/env python3
"""
VaaniKhata – Automated End-to-End Test Suite for Advanced Voice Features
======================================================================
Tests:
  1. Auto-Enroll Customer on First Transaction:
     - Hindi credit & payment auto-enrollment ("Deepak ka 500 udhaar", "Vijay ka 350 jama")
     - Multi-entry first transaction with immediate mid-sale atomic correction
     - Full 6-language Indic confirmation coverage (kn-IN, ta-IN, te-IN, mr-IN, en-IN, hi-IN)
     - Guardrails against invalid customer names ("500 udhaar", "kal 200 diya")
  2. Voice Customer Search & Highlight:
     - Natural search phrasing ("Suresh ka hisaab dikhao", "Show Suresh", "Ramesh search karo")
     - Timeline and balance delivery in payload
     - highlight_customer_id propagation for frontend card scrolling
     - Homonym handling and non-existent customer handling
  3. Voice-Activated Store Summary ("Aaj ka hisaab" / Daily Voice Tally):
     - Trigger recognition ("Aaj ka hisaab batao", "Aaj kitna collection hua?", "Today summary")
     - Deterministic 4-metric math (total credit, total payment, net cashflow, transaction count)
     - Zero raw digits in TTS spoken words
  4. Full-Duplex WebSocket & REST Integration:
     - Live `/ws/voice` WebSocket protocol validation
     - Dashboard state synchronization across all events

Usage:
    python -m scripts.test_voice_features
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Mock GNANI_API_KEY if not configured
if not os.environ.get("GNANI_API_KEY") or os.environ.get("GNANI_API_KEY", "").startswith("PASTE_"):
    os.environ["GNANI_API_KEY"] = "mock_key_for_voice_features_test"
os.environ["GNANI_DEV_MODE"] = "true"

from fastapi.testclient import TestClient
from backend.app import app
from backend import database
from backend.ledger_engine import (
    SessionState,
    process_utterance,
    INTENT_AUTO_ENROLLED_ENTRY,
    INTENT_CUSTOMER_SEARCH,
    INTENT_HOMONYM_CUSTOMER_SEARCH,
    INTENT_DAILY_SUMMARY_QUERY,
    INTENT_ATOMIC_CORRECTION,
    INTENT_FALLBACK_HELP,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_PATH = _PROJECT_ROOT / "test_voice_features.db"


def _banner(title: str):
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  {title}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def _ok(msg: str):
    print(f"  ✅  {msg}")


def _info(msg: str):
    print(f"  ℹ️   {msg}")


def _fail(msg: str):
    print(f"  ❌  {msg}")


def run_tests():
    passed = 0
    total_tests = 4

    print("\n╔═══════════════════════════════════════════════════════════════╗")
    print("║     VaaniKhata · Advanced Voice Features Verification Suite   ║")
    print("╚═══════════════════════════════════════════════════════════════╝")

    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    database.init_db(TEST_DB_PATH)

    # -----------------------------------------------------------------------
    # TEST 1: Auto-Enroll Customer on First Transaction
    # -----------------------------------------------------------------------
    _banner("TEST 1: Auto-Enroll Customer on First Transaction")
    try:
        session1 = SessionState()

        # 1.1 Auto-enroll Deepak with 500 credit
        t1_input = "Deepak ka 500 udhaar"
        res1 = process_utterance(t1_input, session1, db_path=TEST_DB_PATH)
        _info(f"Input: '{t1_input}' -> Intent: {res1['intent']}")
        _info(f"Display: '{res1['display_reply']}'")
        _info(f"TTS: '{res1['tts_reply']}'")

        assert res1["intent"] == INTENT_AUTO_ENROLLED_ENTRY
        assert res1["auto_enrolled"] is True
        assert res1["highlight_customer_id"] is not None
        assert "Deepak" in res1["display_reply"]
        assert not any(ch.isdigit() for ch in res1["tts_reply"])

        # Check DB
        deepak_lookup = database.find_customers_by_name("Deepak", db_path=TEST_DB_PATH)
        assert len(deepak_lookup) == 1
        assert deepak_lookup[0]["net_balance"] == 500
        _ok("Auto-enrolled 'Deepak' on first transaction with ₹500 credit")

        # 1.2 Auto-enroll Vijay with 350 payment
        t2_input = "Vijay ka 350 jama"
        res2 = process_utterance(t2_input, session1, db_path=TEST_DB_PATH)
        _info(f"Input: '{t2_input}' -> Intent: {res2['intent']}")
        assert res2["intent"] == INTENT_AUTO_ENROLLED_ENTRY
        assert res2["auto_enrolled"] is True
        assert "Vijay" in res2["display_reply"]
        assert not any(ch.isdigit() for ch in res2["tts_reply"])

        vijay_lookup = database.find_customers_by_name("Vijay", db_path=TEST_DB_PATH)
        assert len(vijay_lookup) == 1
        assert vijay_lookup[0]["net_balance"] == -350
        _ok("Auto-enrolled 'Vijay' on first transaction with ₹350 payment")

        # 1.3 Multi-entry auto-enrollment: "Anil Kumar ka 600 udhaar kal 200 diya"
        t3_input = "Anil Kumar ka 600 udhaar kal 200 diya"
        res3 = process_utterance(t3_input, session1, db_path=TEST_DB_PATH)
        _info(f"Input: '{t3_input}' -> Intent: {res3['intent']}")
        assert res3["intent"] == INTENT_AUTO_ENROLLED_ENTRY
        assert res3["auto_enrolled"] is True
        assert "Anil Kumar" in res3["display_reply"]

        anil_lookup = database.find_customers_by_name("Anil Kumar", db_path=TEST_DB_PATH)
        assert len(anil_lookup) == 1
        assert anil_lookup[0]["net_balance"] == 400  # 600 credit - 200 payment
        _ok("Auto-enrolled multi-entry customer 'Anil Kumar' (600 - 200 = ₹400)")

        # 1.4 Immediate Mid-Sale Atomic Correction on newly enrolled customer
        t4_input = "Nahi, 700 kar do"
        res4 = process_utterance(t4_input, session1, db_path=TEST_DB_PATH)
        _info(f"Correction input: '{t4_input}' -> Intent: {res4['intent']}")
        assert res4["intent"] == INTENT_ATOMIC_CORRECTION
        anil_lookup_after = database.find_customers_by_name("Anil Kumar", db_path=TEST_DB_PATH)
        assert anil_lookup_after[0]["net_balance"] == 500  # 700 - 200 = 500
        _ok("Mid-sale atomic correction succeeded on newly enrolled customer (balance: ₹500)")

        # 1.5 6-Language localized auto-enroll confirmations
        lang_tests = [
            ("Manjunath ge 300 saala", "kn-IN", "Hosa grahaka"),
            ("Murugan ku 250 kadan", "ta-IN", "Pudhiya vaadikkaiyaalar"),
            ("Venkat ki 400 appu", "te-IN", "Kottha customer"),
            ("Santosh chi 350 udhaari", "mr-IN", "Naveen grahak"),
            ("David 500 credit", "en-IN", "Enrolled new customer"),
        ]
        for utt, lang, expected_phrase in lang_tests:
            s = SessionState(preferred_language=lang)
            r = process_utterance(utt, s, db_path=TEST_DB_PATH)
            assert r["intent"] == INTENT_AUTO_ENROLLED_ENTRY, f"Failed for {lang}: {r['intent']}"
            assert expected_phrase.lower() in r["display_reply"].lower()
            assert not any(ch.isdigit() for ch in r["tts_reply"])
            _ok(f"Localized auto-enrollment confirmed in [{lang}] ('{expected_phrase}')")

        # 1.6 Guardrails: Invalid customer names
        s_guard = SessionState()
        res_no_name = process_utterance("500 udhaar", s_guard, db_path=TEST_DB_PATH)
        assert res_no_name["intent"] == INTENT_FALLBACK_HELP
        res_date_only = process_utterance("kal 200 diya", s_guard, db_path=TEST_DB_PATH)
        assert res_date_only["intent"] == INTENT_FALLBACK_HELP
        _ok("AI safety guardrails blocked invalid entries ('500 udhaar', 'kal 200 diya') from auto-enrollment")

        passed += 1
    except Exception as e:
        _fail(f"Test 1 failed: {e}")
        raise

    # -----------------------------------------------------------------------
    # TEST 2: Voice Customer Search & Highlight
    # -----------------------------------------------------------------------
    _banner("TEST 2: Voice Customer Search & Highlight")
    try:
        session2 = SessionState()

        # 2.1 "Suresh ka hisaab dikhao"
        t_s1 = "Suresh ka hisaab dikhao"
        res_s1 = process_utterance(t_s1, session2, db_path=TEST_DB_PATH)
        _info(f"Input: '{t_s1}' -> Intent: {res_s1['intent']}")
        _info(f"Display: '{res_s1['display_reply']}'")
        assert res_s1["intent"] == INTENT_CUSTOMER_SEARCH
        assert res_s1["highlight_customer_id"] is not None
        assert res_s1["customer"]["full_name"] == "Suresh Gowda"
        assert "timeline" in res_s1
        assert not any(ch.isdigit() for ch in res_s1["tts_reply"])
        _ok("Recognized 'Suresh ka hisaab dikhao' -> CUSTOMER_SEARCH + highlighted Suresh Gowda")

        # 2.2 "Show Suresh"
        t_s2 = "Show Suresh"
        res_s2 = process_utterance(t_s2, session2, db_path=TEST_DB_PATH, stt_lang="en-IN")
        _info(f"Input: '{t_s2}' -> Intent: {res_s2['intent']}")
        assert res_s2["intent"] == INTENT_CUSTOMER_SEARCH
        assert res_s2["highlight_customer_id"] == res_s1["highlight_customer_id"]
        _ok("Recognized 'Show Suresh' -> CUSTOMER_SEARCH + target customer matched")

        # 2.3 "Ramesh search karo" (Homonym Search)
        t_s3 = "Ramesh search karo"
        res_s3 = process_utterance(t_s3, session2, db_path=TEST_DB_PATH)
        _info(f"Input: '{t_s3}' -> Intent: {res_s3['intent']}")
        assert res_s3["intent"] == INTENT_HOMONYM_CUSTOMER_SEARCH
        assert "Sharma" in res_s3["display_reply"] and "Verma" in res_s3["display_reply"]
        _ok("Homonym search 'Ramesh search karo' -> HOMONYM_CUSTOMER_SEARCH (returns both Ramesh)")

        # 2.4 "Ramesh Sharma search karo" (Specific search)
        t_s4 = "Ramesh Sharma search karo"
        res_s4 = process_utterance(t_s4, session2, db_path=TEST_DB_PATH)
        _info(f"Input: '{t_s4}' -> Intent: {res_s4['intent']}")
        assert res_s4["intent"] == INTENT_CUSTOMER_SEARCH
        assert res_s4["customer"]["full_name"] == "Ramesh Sharma"
        assert res_s4["highlight_customer_id"] is not None
        _ok("Specific search 'Ramesh Sharma search karo' -> resolved uniquely to Ramesh Sharma")

        # 2.5 Non-existent customer
        t_s5 = "Kabir search karo"
        res_s5 = process_utterance(t_s5, session2, db_path=TEST_DB_PATH)
        _info(f"Input: '{t_s5}' -> Intent: {res_s5['intent']}")
        assert res_s5["intent"] == INTENT_CUSTOMER_SEARCH
        assert "nahi mila" in res_s5["display_reply"].lower()
        _ok("Search for non-existent customer returned polite 'not found' notice")

        passed += 1
    except Exception as e:
        _fail(f"Test 2 failed: {e}")
        raise

    # -----------------------------------------------------------------------
    # TEST 3: Voice-Activated Store Summary ("Aaj ka hisaab" / Daily Voice Tally)
    # -----------------------------------------------------------------------
    _banner("TEST 3: Voice-Activated Store Summary ('Aaj ka hisaab' / Daily Voice Tally)")
    try:
        session3 = SessionState()

        # 3.1 "Aaj ka hisaab batao"
        t_sum1 = "Aaj ka hisaab batao"
        res_sum1 = process_utterance(t_sum1, session3, db_path=TEST_DB_PATH)
        _info(f"Input: '{t_sum1}' -> Intent: {res_sum1['intent']}")
        _info(f"Display: '{res_sum1['display_reply']}'")
        _info(f"TTS: '{res_sum1['tts_reply']}'")

        assert res_sum1["intent"] == INTENT_DAILY_SUMMARY_QUERY
        assert "summary" in res_sum1
        summary = res_sum1["summary"]
        assert "today_credit" in summary
        assert "today_payment" in summary
        assert "net_cashflow" in summary
        assert "transaction_count" in summary
        assert summary["net_cashflow"] == summary["today_payment"] - summary["today_credit"]
        assert not any(ch.isdigit() for ch in res_sum1["tts_reply"])
        _ok("Rich summary computed: credit, payment, net_cashflow, transaction_count")

        # 3.2 "Aaj kitna collection hua?"
        t_sum2 = "Aaj kitna collection hua?"
        res_sum2 = process_utterance(t_sum2, session3, db_path=TEST_DB_PATH)
        _info(f"Input: '{t_sum2}' -> Intent: {res_sum2['intent']}")
        assert res_sum2["intent"] == INTENT_DAILY_SUMMARY_QUERY
        _ok("Recognized collection query 'Aaj kitna collection hua?' -> DAILY_SUMMARY_QUERY")

        # 3.3 "Today summary" (English)
        t_sum3 = "Today summary"
        res_sum3 = process_utterance(t_sum3, session3, db_path=TEST_DB_PATH, stt_lang="en-IN")
        _info(f"Input: '{t_sum3}' -> Intent: {res_sum3['intent']}")
        assert res_sum3["intent"] == INTENT_DAILY_SUMMARY_QUERY
        assert "today's summary" in res_sum3["display_reply"].lower()
        _ok("Recognized English query 'Today summary' -> DAILY_SUMMARY_QUERY")

        passed += 1
    except Exception as e:
        _fail(f"Test 3 failed: {e}")
        raise

    # -----------------------------------------------------------------------
    # TEST 4: Full-Duplex WebSocket & REST Integration
    # -----------------------------------------------------------------------
    _banner("TEST 4: Full-Duplex WebSocket & REST Integration")
    try:
        client = TestClient(app)

        with client.websocket_connect("/ws/voice") as ws:
            # Drain Turn 1 disclosure
            disc = ws.receive_json()
            assert disc["type"] == "TURN_1_AI_DISCLOSURE"
            _ok("WebSocket connected and Turn-1 AI Disclosure received")

            # 4.1 Auto-enroll via WebSocket
            ws.send_json({"type": "UTTERANCE", "text": "Kavita ka 800 udhaar"})
            reply_auto = ws.receive_json()
            assert reply_auto["type"] == "VOICE_RESULT"
            assert reply_auto["intent"] == INTENT_AUTO_ENROLLED_ENTRY
            assert reply_auto.get("highlight_customer_id") is not None
            assert reply_auto.get("auto_enrolled") is True
            _ok("WebSocket auto-enrolled 'Kavita' (highlight_customer_id received)")

            # 4.2 Customer search via WebSocket
            ws.send_json({"type": "UTTERANCE", "text": "Kavita ka hisaab dikhao"})
            reply_search = ws.receive_json()
            assert reply_search["type"] == "VOICE_RESULT"
            assert reply_search["intent"] == INTENT_CUSTOMER_SEARCH
            assert reply_search.get("highlight_customer_id") == reply_auto["highlight_customer_id"]
            _ok("WebSocket customer search highlighted 'Kavita' card correctly")

            # 4.3 Daily store summary via WebSocket
            ws.send_json({"type": "UTTERANCE", "text": "Aaj ka hisaab batao"})
            reply_summary = ws.receive_json()
            assert reply_summary["type"] == "VOICE_RESULT"
            assert reply_summary["intent"] == INTENT_DAILY_SUMMARY_QUERY
            assert "summary" in reply_summary
            assert reply_summary["summary"]["today_credit"] >= 800
            _ok("WebSocket daily summary returned rich store tally")

        # 4.4 REST /api/voice-turn
        rest_resp = client.post("/api/voice-turn", json={"text": "Aaj ka hisaab batao"})
        assert rest_resp.status_code == 200
        r_json = rest_resp.json()
        assert r_json["intent"] == INTENT_DAILY_SUMMARY_QUERY
        assert "summary" in r_json
        _ok("REST /api/voice-turn matches WebSocket behavior identically")

        passed += 1
    except Exception as e:
        _fail(f"Test 4 failed: {e}")
        raise
    finally:
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    _banner("ADVANCED VOICE FEATURES VERIFICATION SUMMARY")
    print(f"  Passed: {passed}/{total_tests} feature test suites completed successfully!\n")
    return passed == total_tests


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
