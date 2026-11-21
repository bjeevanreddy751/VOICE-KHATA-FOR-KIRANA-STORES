#!/usr/bin/env python3
"""
VaaniKhata – Automated Phase 3 Ledger Engine Verification Suite
================================================================
Tests:
  1. Numeral Normalizer Matrix (Hindi/Kannada/English idioms, script digits)
  2. Turn 1: Multi-Entry & Spoken Homonym Clarification Trigger
  3. Turn 2: Disambiguation Resolution (₹140 net balance, 0 raw digits in TTS)
  4. Turn 3: Atomic Mid-Sale Voice Correction (₹340 -> ₹430 => ₹230 net balance)
  5. Turn 4A: Customer Balance Query (₹230 / 'do sau tees')
  6. Turn 4B: Fast-Path Daily Store Summary (Today's credit == ₹710)
  7. Direct Unique Customer Entry (Suresh ₹280 - ₹150 payment = ₹130)
  8. Responsible AI Money Guardrail & Sub-25ms Latency Benchmark

Usage:
    cd vaanikhata/
    python -m scripts.test_ledger_engine
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path & Environment Setup
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Provide mock key for offline test suite if not set in .env
if not os.environ.get("GNANI_API_KEY") or os.environ.get("GNANI_API_KEY", "").startswith("PASTE_"):
    os.environ["GNANI_API_KEY"] = "mock_key_for_phase3_ledger_engine_suite"

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

from backend import database
from backend.database import fetch_dashboard_state, get_db, reset_demo_db
from backend.ledger_engine import (
    INTENT_ATOMIC_CORRECTION,
    INTENT_CUSTOMER_BALANCE_QUERY,
    INTENT_DAILY_SUMMARY_QUERY,
    INTENT_DISAMBIGUATION_RESOLVED,
    INTENT_GUARDRAIL_BLOCKED,
    INTENT_HOMONYM_CLARIFICATION_REQUIRED,
    INTENT_LOGGED_ENTRY,
    SessionState,
    process_utterance,
)
from backend.numeral_parser import (
    normalize_spoken_numbers,
    number_to_spoken_hindi,
    resolve_relative_date,
)

TEST_DB_NAME = "test_ledger_vaanikhata.db"
TEST_DB_PATH = _PROJECT_ROOT / TEST_DB_NAME


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


def cleanup_test_db() -> None:
    for p in [TEST_DB_PATH, Path(f"{TEST_DB_PATH}-wal"), Path(f"{TEST_DB_PATH}-shm")]:
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def run_all_tests() -> bool:
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}╔═══════════════════════════════════════════════════════════════╗")
    print(f"║     VaaniKhata · Phase 3 Stateful Ledger & Normalizer Suite   ║")
    print(f"╚═══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    cleanup_test_db()
    passed = 0
    total = 8
    latencies: list[float] = []

    try:
        # Initialize test DB cleanly
        database.init_db(TEST_DB_PATH)
        reset_demo_db(TEST_DB_PATH)
        session = SessionState()

        # -------------------------------------------------------------------
        # TEST 1: Numeral Normalizer Matrix
        # -------------------------------------------------------------------
        _banner("TEST 1: Code-Mix Indic Numeral Normalizer Matrix")
        test_cases = [
            ("teen sau chaalis", "340"),
            ("three-forty", "340"),
            ("three forty", "340"),
            ("३४०", "340"),
            ("saadhe teen sau", "350"),
            ("dedh sau", "150"),
            ("eradu nooru", "200"),
            ("Ramesh ka teen sau chaalis udhaar, kal do sau diya tha", "Ramesh ka 340 udhaar, kal 200 diya tha"),
        ]

        for inp, expected in test_cases:
            res = normalize_spoken_numbers(inp)
            _info(f"'{inp}' -> '{res}'")
            assert expected in res, f"Expected '{expected}' in '{res}'"

        spoken_230 = number_to_spoken_hindi(230)
        _info(f"number_to_spoken_hindi(230) -> '{spoken_230}'")
        assert spoken_230 == "do sau tees", f"Expected 'do sau tees', got '{spoken_230}'"
        assert not any(ch.isdigit() for ch in spoken_230), "Spoken Hindi string must contain zero ASCII digits!"

        _ok("Hindi, Hinglish, Kannada, and English numerals accurately mapped")
        _ok("Devanagari digits '३४०' normalized to ASCII '340'")
        _ok("number_to_spoken_hindi(230) produces 'do sau tees' with 0 digits")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 2: Turn 1 (Multi-Entry + Homonym Clarification Trigger)
        # -------------------------------------------------------------------
        _banner("TEST 2: Turn 1 · Multi-Entry Speech + Homonym Clarification")
        t1_input = "Ramesh ka teen sau chaalis udhaar, kal do sau diya tha"
        res1 = process_utterance(t1_input, session, db_path=TEST_DB_PATH)
        latencies.append(res1["engine_latency_ms"])

        _info(f"Input       : '{t1_input}'")
        _info(f"Normalized  : '{res1['normalized_transcript']}'")
        _info(f"Intent      : {res1['intent']}")
        _info(f"Display     : {res1['display_reply']}")
        _info(f"TTS Spoken  : {res1['tts_reply']}")
        _info(f"Latency     : {res1['engine_latency_ms']} ms")

        assert res1["intent"] == INTENT_HOMONYM_CLARIFICATION_REQUIRED
        assert res1["has_pending_disambiguation"] is True
        assert session.pending_disambiguation is not None

        # Verify DB balance of Ramesh Sharma is STILL ₹0 (no premature write)
        custs = database.find_customers_by_name("Ramesh Sharma", db_path=TEST_DB_PATH)
        assert custs[0]["net_balance"] == 0, f"Expected balance 0, got {custs[0]['net_balance']}"

        _ok("Intent correctly flagged as HOMONYM_CLARIFICATION_REQUIRED")
        _ok("Pending disambiguation stored in session; database write safely deferred")
        _ok("Ramesh Sharma balance remains strictly ₹0")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 3: Turn 2 (Disambiguation Resolution)
        # -------------------------------------------------------------------
        _banner("TEST 3: Turn 2 · Disambiguation Resolution ('Sharma')")
        t2_input = "Sharma"
        res2 = process_utterance(t2_input, session, db_path=TEST_DB_PATH)
        latencies.append(res2["engine_latency_ms"])

        _info(f"Input       : '{t2_input}'")
        _info(f"Intent      : {res2['intent']}")
        _info(f"Display     : {res2['display_reply']}")
        _info(f"TTS Spoken  : {res2['tts_reply']}")
        _info(f"Latency     : {res2['engine_latency_ms']} ms")

        assert res2["intent"] == INTENT_DISAMBIGUATION_RESOLVED
        assert res2["has_pending_disambiguation"] is False
        assert session.pending_disambiguation is None

        # Check DB balance: ₹0 + ₹340 - ₹200 = ₹140
        sharma = database.find_customers_by_name("Ramesh Sharma", db_path=TEST_DB_PATH)[0]
        assert sharma["net_balance"] == 140, f"Expected 140, got {sharma['net_balance']}"

        # Assert zero digits in TTS reply
        assert not any(ch.isdigit() for ch in res2["tts_reply"]), "TTS reply contains raw digits!"
        assert "ek sau chaalis" in res2["tts_reply"]

        _ok("Disambiguation resolved cleanly to Ramesh Sharma (MG Road)")
        _ok("Multi-entry atomic write executed: ₹0 + ₹340 - ₹200 = ₹140")
        _ok("TTS reply contains 'ek sau chaalis' with strictly 0 raw ASCII digits")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 4: Turn 3 (Atomic Mid-Sale Voice Correction)
        # -------------------------------------------------------------------
        _banner("TEST 4: Turn 3 · Atomic Voice Correction ('Nahi, 430 kar do')")
        t3_input = "Nahi, 430 kar do"
        res3 = process_utterance(t3_input, session, db_path=TEST_DB_PATH)
        latencies.append(res3["engine_latency_ms"])

        _info(f"Input       : '{t3_input}'")
        _info(f"Intent      : {res3['intent']}")
        _info(f"Display     : {res3['display_reply']}")
        _info(f"TTS Spoken  : {res3['tts_reply']}")
        _info(f"Latency     : {res3['engine_latency_ms']} ms")

        assert res3["intent"] == INTENT_ATOMIC_CORRECTION

        # Check DB balance: ₹430 - ₹200 = ₹230
        sharma_after_corr = database.find_customers_by_name("Ramesh Sharma", db_path=TEST_DB_PATH)[0]
        assert sharma_after_corr["net_balance"] == 230, f"Expected 230, got {sharma_after_corr['net_balance']}"

        # Verify old 340 row is REVERSED
        with get_db(TEST_DB_PATH) as conn:
            rev_row = conn.execute(
                "SELECT * FROM transactions WHERE customer_id = ? AND status = 'REVERSED'",
                (sharma["id"],),
            ).fetchone()
            assert rev_row is not None and rev_row["amount"] == 340

        assert not any(ch.isdigit() for ch in res3["tts_reply"]), "TTS reply contains raw digits!"
        assert "do sau tees" in res3["tts_reply"]

        _ok("Mid-sale voice correction atomically reversed ₹340 row")
        _ok("New row with ₹430 inserted; Ramesh Sharma balance updated to ₹230")
        _ok("TTS reply verified: 'do sau tees' with zero raw digits")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 5: Turn 4A (Customer Balance Query)
        # -------------------------------------------------------------------
        _banner("TEST 5: Turn 4A · Customer Balance Query ('Ramesh Sharma ka total?')")
        t4a_input = "Ramesh Sharma ka total?"
        res4a = process_utterance(t4a_input, session, db_path=TEST_DB_PATH)
        latencies.append(res4a["engine_latency_ms"])

        _info(f"Input       : '{t4a_input}'")
        _info(f"Intent      : {res4a['intent']}")
        _info(f"Display     : {res4a['display_reply']}")
        _info(f"TTS Spoken  : {res4a['tts_reply']}")
        _info(f"Latency     : {res4a['engine_latency_ms']} ms")

        assert res4a["intent"] == INTENT_CUSTOMER_BALANCE_QUERY
        assert "230" in res4a["display_reply"]
        assert "do sau tees" in res4a["tts_reply"]
        assert not any(ch.isdigit() for ch in res4a["tts_reply"])

        _ok("Fast-path balance query returned Ramesh Sharma balance ₹230")
        _ok("TTS response spoken as 'do sau tees'")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 6: Turn 4B (Fast-Path Daily Store Summary)
        # -------------------------------------------------------------------
        _banner("TEST 6: Turn 4B · Daily Store Summary ('Aaj kitna udhaar gaya?')")
        t4b_input = "Aaj kitna udhaar gaya?"
        res4b = process_utterance(t4b_input, session, db_path=TEST_DB_PATH)
        latencies.append(res4b["engine_latency_ms"])

        _info(f"Input       : '{t4b_input}'")
        _info(f"Intent      : {res4b['intent']}")
        _info(f"Display     : {res4b['display_reply']}")
        _info(f"TTS Spoken  : {res4b['tts_reply']}")
        _info(f"Latency     : {res4b['engine_latency_ms']} ms")

        assert res4b["intent"] == INTENT_DAILY_SUMMARY_QUERY
        # Today's active credit = Suresh Gowda (280) + Ramesh Sharma (430) = 710
        summary = database.get_daily_summary(db_path=TEST_DB_PATH)
        _info(f"DB Daily Summary: Credit=₹{summary['today_credit']}, Payment=₹{summary['today_payment']}")
        assert summary["today_credit"] == 710, f"Expected 710, got {summary['today_credit']}"
        assert "710" in res4b["display_reply"]
        assert not any(ch.isdigit() for ch in res4b["tts_reply"])

        _ok("Daily store summary calculated directly via SQL index")
        _ok("Today's credit total == ₹710 (280 Suresh + 430 Ramesh)")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 7: Direct Unique Customer Entry
        # -------------------------------------------------------------------
        _banner("TEST 7: Direct Unique Customer Entry ('Suresh ka 150 jama')")
        t7_input = "Suresh ka 150 jama"
        res7 = process_utterance(t7_input, session, db_path=TEST_DB_PATH)
        latencies.append(res7["engine_latency_ms"])

        _info(f"Input       : '{t7_input}'")
        _info(f"Intent      : {res7['intent']}")
        _info(f"Display     : {res7['display_reply']}")
        _info(f"TTS Spoken  : {res7['tts_reply']}")
        _info(f"Latency     : {res7['engine_latency_ms']} ms")

        assert res7["intent"] == INTENT_LOGGED_ENTRY

        # Suresh started at ₹280; 150 payment leaves ₹130
        gowda = database.find_customers_by_name("Suresh Gowda", db_path=TEST_DB_PATH)[0]
        assert gowda["net_balance"] == 130, f"Expected 130, got {gowda['net_balance']}"
        assert not any(ch.isdigit() for ch in res7["tts_reply"])

        _ok("Direct payment logged for Suresh Gowda without disambiguation")
        _ok("Suresh balance dropped deterministically from ₹280 to ₹130")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 8: Responsible AI Money Guardrail & Speed Check
        # -------------------------------------------------------------------
        _banner("TEST 8: Responsible AI Guardrail & Latency Benchmark")
        t8_input = "Ramesh ko dhamki bhejo ya loan do"
        res8 = process_utterance(t8_input, session, db_path=TEST_DB_PATH)
        latencies.append(res8["engine_latency_ms"])

        _info(f"Input       : '{t8_input}'")
        _info(f"Intent      : {res8['intent']}")
        _info(f"Display     : {res8['display_reply']}")
        _info(f"Latency     : {res8['engine_latency_ms']} ms")

        assert res8["intent"] == INTENT_GUARDRAIL_BLOCKED
        assert "loan ya byaaj" in res8["display_reply"]

        avg_latency = sum(latencies) / len(latencies)
        _info(f"All turn latencies (ms): {[round(x, 2) for x in latencies]}")
        _info(f"Average deterministic engine latency: {avg_latency:.2f} ms")
        assert avg_latency < 25.0, f"Average latency {avg_latency:.2f} ms exceeded 25 ms target!"

        _ok("Prohibited lending/threat request blocked cleanly by AI guardrail")
        _ok(f"Sub-25ms benchmark verified (Average: {avg_latency:.2f} ms)")
        passed += 1

        # -------------------------------------------------------------------
        # Final Summary
        # -------------------------------------------------------------------
        _banner("PHASE 3 VERIFICATION SUMMARY")
        print(f"  {Fore.GREEN}{Style.BRIGHT}Passed: {passed}/{total} tests completed successfully!{Style.RESET_ALL}\n")
        return True

    except Exception as exc:
        _fail(f"Test suite failed with error: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cleanup_test_db()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
