#!/usr/bin/env python3
"""
VaaniKhata – Automated Phase 2 Database & Security Verification Suite
======================================================================
Tests:
  1. Synthetic Seed Data & Initial Balances (Pitch deck math: ₹0, ₹150, ₹280)
  2. Homonym & Smart Name Resolution (Ramesh -> 2 matches, Sharma -> 1 match)
  3. Multi-entry Atomic ACID Transactions (₹0 + ₹340 - ₹200 = ₹140)
  4. Atomic Rollback & Correction Replacement (₹340 -> ₹430 => net ₹230)
  5. DPDP AES-256 Encryption at Rest (Plaintext absent in raw SQLite storage)
  6. Responsible AI Opt-In Guardrail (Block reminders for opted-out users)
  7. DPDP Act 1-Click Voice Transcript Purge (Zero leftover PII logs)

Usage:
    cd vaanikhata/
    python -m scripts.test_database
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import sys
from pathlib import Path

# Provide a mock key if running in an environment without .env filled
if not os.environ.get("GNANI_API_KEY") or os.environ.get("GNANI_API_KEY", "").startswith("PASTE_"):
    os.environ["GNANI_API_KEY"] = "mock_key_for_phase2_db_verification_suite"

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
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

from backend.database import (
    add_transactions_atomic,
    build_polite_reminder,
    decrypt_text,
    encrypt_text,
    fetch_dashboard_state,
    find_customers_by_name,
    get_daily_summary,
    get_db,
    init_db,
    log_encrypted_transcript,
    purge_demo_transcripts,
    reset_demo_db,
    resolve_db_path,
    reverse_and_replace_transaction,
    set_customer_opt_in,
)

TEST_DB_NAME = "test_vaanikhata.db"
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
    """Safely remove test database and SQLite journal files."""
    for p in [
        TEST_DB_PATH,
        Path(f"{TEST_DB_PATH}-wal"),
        Path(f"{TEST_DB_PATH}-shm"),
    ]:
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def run_all_tests() -> bool:
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}╔═══════════════════════════════════════════════════════════════╗")
    print(f"║     VaaniKhata · Phase 2 Automated Ledger & DPDP Suite       ║")
    print(f"╚═══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    cleanup_test_db()
    passed = 0
    total = 7

    try:
        # -------------------------------------------------------------------
        # TEST 1: Seed check
        # -------------------------------------------------------------------
        _banner("TEST 1: Synthetic Seed Data & Initial Balances")
        init_db(TEST_DB_PATH)
        state = fetch_dashboard_state(TEST_DB_PATH)
        customers = {c["full_name"]: c for c in state["customers"]}

        assert len(customers) == 4, f"Expected 4 customers, found {len(customers)}"
        assert "Ramesh Sharma" in customers, "Ramesh Sharma not found"
        assert "Ramesh Verma" in customers, "Ramesh Verma not found"
        assert "Suresh Gowda" in customers, "Suresh Gowda not found"
        assert "Lakshmi Devi" in customers, "Lakshmi Devi not found"

        sharma_bal = customers["Ramesh Sharma"]["net_balance"]
        verma_bal = customers["Ramesh Verma"]["net_balance"]
        gowda_bal = customers["Suresh Gowda"]["net_balance"]
        lakshmi_bal = customers["Lakshmi Devi"]["net_balance"]

        assert sharma_bal == 0, f"Ramesh Sharma balance expected 0, got {sharma_bal}"
        assert verma_bal == 150, f"Ramesh Verma balance expected 150, got {verma_bal}"
        assert gowda_bal == 280, f"Suresh Gowda balance expected 280, got {gowda_bal}"
        assert lakshmi_bal == 0, f"Lakshmi Devi balance expected 0, got {lakshmi_bal}"

        _ok("4 Synthetic Kirana customers seeded accurately")
        _ok("Ramesh Sharma balance == ₹0 (Ready for Turn 1 demo math)")
        _ok("Ramesh Verma balance == ₹150 (Yesterday CREDIT active, opt-out)")
        _ok("Suresh Gowda balance == ₹280, Lakshmi Devi balance == ₹0")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 2: Homonym & Smart Name Resolution
        # -------------------------------------------------------------------
        _banner("TEST 2: Homonym Disambiguation & Smart Lookup")
        ramesh_matches = find_customers_by_name("Ramesh", TEST_DB_PATH)
        _info(f"Query 'Ramesh' matched: {[m['full_name'] for m in ramesh_matches]}")
        assert len(ramesh_matches) == 2, f"Expected 2 matches for 'Ramesh', got {len(ramesh_matches)}"

        sharma_matches = find_customers_by_name("Sharma", TEST_DB_PATH)
        _info(f"Query 'Sharma' matched: {[m['full_name'] for m in sharma_matches]}")
        assert len(sharma_matches) == 1, f"Expected 1 match for 'Sharma', got {len(sharma_matches)}"
        assert sharma_matches[0]["full_name"] == "Ramesh Sharma"

        full_matches = find_customers_by_name("Ramesh Sharma", TEST_DB_PATH)
        assert len(full_matches) == 1 and full_matches[0]["full_name"] == "Ramesh Sharma"

        landmark_matches = find_customers_by_name("MG Road", TEST_DB_PATH)
        assert len(landmark_matches) == 1 and landmark_matches[0]["full_name"] == "Ramesh Sharma"

        _ok("Homonym 'Ramesh' resolved to 2 candidates (triggers voice disambiguation)")
        _ok("Unique surname 'Sharma' resolved deterministically to [Ramesh Sharma]")
        _ok("Exact full name and landmark lookups succeeded")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 3: Multi-entry ACID math (₹0 -> ₹140)
        # -------------------------------------------------------------------
        _banner("TEST 3: Multi-Entry ACID Math (+₹340 credit, -₹200 payment)")
        sharma_id = customers["Ramesh Sharma"]["id"]
        today_str = datetime.date.today().isoformat()
        yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        raw_note_turn1 = "Ramesh ka 340 udhaar kal ka 200 jama"

        entries = [
            {"amount": 340, "tx_type": "CREDIT", "tx_date": today_str, "relative_label": "Today"},
            {"amount": 200, "tx_type": "PAYMENT", "tx_date": yesterday_str, "relative_label": "Yesterday (kal)"},
        ]

        tx_res = add_transactions_atomic(sharma_id, entries, raw_note_turn1, TEST_DB_PATH)
        primary_tx_id = tx_res["primary_tx_id"]
        new_balance = tx_res["new_balance"]

        _info(f"Primary tx ID: {primary_tx_id}, Inserted IDs: {tx_res['inserted_ids']}")
        _info(f"New balance: ₹{new_balance}")

        assert new_balance == 140, f"Expected net balance 140, got {new_balance}"
        assert len(tx_res["inserted_ids"]) == 2

        # Check daily summary reflects today's credit
        summary = get_daily_summary(today_str, TEST_DB_PATH)
        _info(f"Today's active summary: Credit=₹{summary['today_credit']}, Payment=₹{summary['today_payment']}")
        assert summary["today_credit"] >= 340

        _ok("Multi-entry atomic write committed inside single ACID transaction")
        _ok("Deterministic ledger math verified: ₹0 + ₹340 - ₹200 = ₹140")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 4: Atomic rollback & correction (₹340 -> ₹430 => net ₹230)
        # -------------------------------------------------------------------
        _banner("TEST 4: Atomic Rollback & Correction (₹340 -> ₹430 => net ₹230)")
        raw_note_turn2 = "Nahi, 430 tha"
        corr_res = reverse_and_replace_transaction(primary_tx_id, 430, raw_note_turn2, TEST_DB_PATH)

        _info(f"Old amount: ₹{corr_res['old_amount']} (REVERSED)")
        _info(f"New amount: ₹{corr_res['new_amount']} (ACTIVE, replaces tx #{primary_tx_id})")
        _info(f"Updated customer balance: ₹{corr_res['new_balance']}")

        assert corr_res["old_amount"] == 340
        assert corr_res["new_amount"] == 430
        assert corr_res["new_balance"] == 230, f"Expected 230, got {corr_res['new_balance']}"

        # Verify old row is marked REVERSED and replacement is linked in DB
        with get_db(TEST_DB_PATH) as conn:
            old_row = conn.execute("SELECT * FROM transactions WHERE id = ?", (primary_tx_id,)).fetchone()
            new_row = conn.execute("SELECT * FROM transactions WHERE id = ?", (corr_res["new_tx_id"],)).fetchone()

            assert old_row["status"] == "REVERSED", "Old transaction was not marked REVERSED"
            assert new_row["status"] == "ACTIVE", "New transaction is not ACTIVE"
            assert new_row["replaces_tx_id"] == primary_tx_id, "replaces_tx_id audit link broken"
            assert new_row["relative_label"] == "Today (Corrected)"

        _ok(f"Old tx #{primary_tx_id} successfully marked REVERSED")
        _ok(f"New corrected tx #{corr_res['new_tx_id']} linked via replaces_tx_id")
        _ok("Audit trail preserved with pitch deck math: ₹430 - ₹200 = ₹230")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 5: Encryption at Rest (DPDP Act Compliance)
        # -------------------------------------------------------------------
        _banner("TEST 5: AES-256 Encryption at Rest (DPDP Act Compliance)")
        raw_spoken_text = "Ramesh ka 340 udhaar"
        agent_spoken_reply = "Ramesh ji ka 340 rupaye jod diya hai"

        t_id = log_encrypted_transcript(
            raw_spoken_text,
            agent_spoken_reply,
            intent="ADD_ENTRY",
            latency_ms=412,
            db_path=TEST_DB_PATH,
        )

        # Inspect raw SQLite database directly using raw cursor
        conn_raw = sqlite3.connect(str(TEST_DB_PATH))
        conn_raw.row_factory = sqlite3.Row

        raw_tx_row = conn_raw.execute(
            "SELECT encrypted_raw_note FROM transactions WHERE id = ?", (primary_tx_id,)
        ).fetchone()
        raw_demo_row = conn_raw.execute(
            "SELECT encrypted_transcript, encrypted_response FROM demo_transcripts WHERE id = ?",
            (t_id,),
        ).fetchone()
        conn_raw.close()

        enc_tx_note = raw_tx_row["encrypted_raw_note"]
        enc_transcript = raw_demo_row["encrypted_transcript"]
        enc_reply = raw_demo_row["encrypted_response"]

        # Assert plaintext NEVER appears in SQLite raw strings
        assert raw_spoken_text not in enc_tx_note, "CRITICAL: Plaintext leaked in transactions table!"
        assert raw_spoken_text not in enc_transcript, "CRITICAL: Plaintext leaked in demo_transcripts table!"
        assert agent_spoken_reply not in enc_reply, "CRITICAL: Plaintext leaked in demo_transcripts reply!"

        # Assert Fernet decrypt recovers plaintext accurately
        dec_tx_note = decrypt_text(enc_tx_note)
        dec_transcript = decrypt_text(enc_transcript)
        dec_reply = decrypt_text(enc_reply)

        assert dec_tx_note == raw_note_turn1
        assert dec_transcript == raw_spoken_text
        assert dec_reply == agent_spoken_reply

        _info(f"Raw cipher sample: {enc_transcript[:36]}... (length: {len(enc_transcript)})")
        _ok("Plaintext notes & transcripts strictly absent from SQLite raw storage")
        _ok("AES-256 Fernet decrypt accurately recovers original spoken notes")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 6: Responsible AI Opt-In Guardrail
        # -------------------------------------------------------------------
        _banner("TEST 6: Responsible AI Reminder Opt-In Guardrail")
        verma_id = customers["Ramesh Verma"]["id"]

        # Ramesh Sharma is opt_in_reminder = 1
        rem_sharma = build_polite_reminder(sharma_id, TEST_DB_PATH)
        _info(f"Ramesh Sharma reminder: allowed={rem_sharma['allowed']}")
        assert rem_sharma["allowed"] is True
        assert "message" in rem_sharma and len(rem_sharma["message"]) > 0

        # Ramesh Verma is opt_in_reminder = 0
        rem_verma = build_polite_reminder(verma_id, TEST_DB_PATH)
        _info(f"Ramesh Verma reminder: allowed={rem_verma['allowed']}")
        assert rem_verma["allowed"] is False
        assert "BLOCKED BY GUARDRAIL" in rem_verma["reason"]
        assert "message" not in rem_verma

        # Toggle Verma's opt-in to True and verify guardrail permits
        set_customer_opt_in(verma_id, True, TEST_DB_PATH)
        rem_verma_after = build_polite_reminder(verma_id, TEST_DB_PATH)
        assert rem_verma_after["allowed"] is True

        # Toggle back to False
        set_customer_opt_in(verma_id, False, TEST_DB_PATH)
        assert build_polite_reminder(verma_id, TEST_DB_PATH)["allowed"] is False

        _ok("Opted-in customer (Sharma) permits polite bilingual reminder")
        _ok("Opted-out customer (Verma) strictly blocked by AI safety guardrail")
        _ok("Dynamic opt-in/opt-out status update verified")
        passed += 1

        # -------------------------------------------------------------------
        # TEST 7: DPDP Act 1-Click Purge
        # -------------------------------------------------------------------
        _banner("TEST 7: DPDP Act 1-Click Voice Transcript Purge")
        dashboard_before = fetch_dashboard_state(TEST_DB_PATH)
        _info(f"Demo transcripts before purge: {dashboard_before['encrypted_transcript_count']}")
        assert dashboard_before["encrypted_transcript_count"] >= 1

        deleted_count = purge_demo_transcripts(TEST_DB_PATH)
        dashboard_after = fetch_dashboard_state(TEST_DB_PATH)
        _info(f"Purged {deleted_count} voice session log(s)")
        _info(f"Demo transcripts after purge: {dashboard_after['encrypted_transcript_count']}")

        assert deleted_count >= 1
        assert dashboard_after["encrypted_transcript_count"] == 0

        _ok(f"DPDP 1-click purge successfully wiped {deleted_count} voice logs")
        _ok("encrypted_transcript_count dropped to exactly 0")
        passed += 1

        # -------------------------------------------------------------------
        # Final Summary
        # -------------------------------------------------------------------
        _banner("PHASE 2 VERIFICATION SUMMARY")
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
