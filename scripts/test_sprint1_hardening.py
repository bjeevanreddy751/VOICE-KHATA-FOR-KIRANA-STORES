#!/usr/bin/env python3
"""
VaaniKhata – Sprint 1 Hardening & Compliance Verification Suite
==============================================================
Tests:
  1. Both-End Session Isolation (X-Session-ID headers prevent tab collisions on pending disambiguation)
  2. Real Client-Side Barge-In Echo (client_halt_ms echoed back, zero hardcoded (<80ms) string)
  3. Dynamic Top-200 Customer Keyterm Roster (seeded names returned, deduplicated, strict 200 cap)
  4. TTS Disk Cache Transparency (tts_cached boolean returned on REST, WebSocket, and gnani_service)

Usage:
    cd vaanikhata/
    python -m scripts.test_sprint1_hardening
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure GNANI_DEV_MODE is enabled to protect live API credits
os.environ["GNANI_DEV_MODE"] = "true"

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
from backend.gnani_service import synthesize_timbre_tts


def _banner(title: str) -> None:
    width = 65
    print(f"\n{Fore.CYAN}{'━' * width}")
    print(f"  {Style.BRIGHT}{title}")
    print(f"{Fore.CYAN}{'━' * width}")


def _ok(msg: str) -> None:
    print(f"  {Fore.GREEN}✅  {msg}")


def _info(msg: str) -> None:
    print(f"  {Fore.YELLOW}ℹ️   {msg}")


def main() -> int:
    print(f"\n{Fore.CYAN}╔{'═' * 63}╗")
    print(f"║     {Fore.GREEN}VaaniKhata · Sprint 1 Hardening & Isolation Suite{Fore.CYAN}         ║")
    print(f"╚{'═' * 63}╝")

    client = TestClient(app)
    passed = 0

    # -------------------------------------------------------------------
    # TEST 1: Session Isolation via X-Session-ID
    # -------------------------------------------------------------------
    _banner("TEST 1: Both-End Session Isolation (X-Session-ID Header)")
    database.reset_demo_db()

    # Session Alpha: trigger homonym clarification for 'Ramesh'
    res_a1 = client.post(
        "/api/voice-turn",
        json={"text": "Ramesh ka 340 udhaar, kal 200 diya tha", "language": "hi-IN"},
        headers={"X-Session-ID": "session_alpha_101"},
    ).json()
    _info(f"Session Alpha Turn 1 Intent: {res_a1['intent']}")
    assert res_a1["intent"] == "HOMONYM_CLARIFICATION_REQUIRED"
    assert res_a1["has_pending_disambiguation"] is True

    # Session Beta: send payment for Suresh Gowda concurrently
    res_b1 = client.post(
        "/api/voice-turn",
        json={"text": "Suresh ka 150 jama", "language": "hi-IN"},
        headers={"X-Session-ID": "session_beta_202"},
    ).json()
    _info(f"Session Beta Turn 1 Intent: {res_b1['intent']}")
    # Session Beta must NOT be waiting on Ramesh disambiguation!
    assert res_b1["intent"] == "LOGGED_ENTRY", f"Expected LOGGED_ENTRY, got {res_b1['intent']}"
    assert res_b1["has_pending_disambiguation"] is False

    # Session Alpha: resolves disambiguation with 'Sharma'
    res_a2 = client.post(
        "/api/voice-turn",
        json={"text": "Sharma", "language": "hi-IN"},
        headers={"X-Session-ID": "session_alpha_101"},
    ).json()
    _info(f"Session Alpha Turn 2 Intent: {res_a2['intent']}")
    assert res_a2["intent"] == "DISAMBIGUATION_RESOLVED"
    assert "140" in res_a2["display_reply"]

    _ok("Distinct X-Session-ID headers completely isolate pending state between tabs")
    passed += 1

    # -------------------------------------------------------------------
    # TEST 2: Real Client-Side Barge-In Echo (No hardcoded string)
    # -------------------------------------------------------------------
    _banner("TEST 2: Real Barge-In Timer Echo (Zero hardcoded (<80ms))")
    with client.websocket_connect("/ws/voice?session_id=test_barge_in_ws") as ws:
        # Await Turn 1 AI disclosure
        disc = ws.receive_json()
        assert disc["type"] == "TURN_1_AI_DISCLOSURE"

        # Send client-measured halt time
        measured_ms = 18.75
        ws.send_json({"type": "BARGE_IN", "client_halt_ms": measured_ms})
        barge_resp = ws.receive_json()
        _info(f"Barge-In Echo: {barge_resp}")

        assert barge_resp["type"] == "TTS_HALTED"
        assert barge_resp["client_halt_ms"] == measured_ms
        assert barge_resp["status"] == "Audio cancelled"

        # Verify completely zero occurrences of hardcoded string
        raw_json = json.dumps(barge_resp)
        assert "<80ms" not in raw_json, "Found hardcoded '<80ms' in response!"
        assert "(<80ms)" not in raw_json, "Found hardcoded '(<80ms)' in response!"

    _ok("BARGE_IN echoes client_halt_ms accurately with zero hardcoded '(<80ms)' string")
    passed += 1

    # -------------------------------------------------------------------
    # TEST 3: Top-200 Customer Keyterm Roster
    # -------------------------------------------------------------------
    _banner("TEST 3: Dynamic Top-200 Customer Keyterm Roster")
    database.reset_demo_db()

    roster = database.get_keyterm_roster(limit=200)
    _info(f"Seeded roster term count: {len(roster)}")
    _info(f"Roster sample: {roster[:8]}")

    assert isinstance(roster, list)
    assert len(roster) <= 200

    # Must contain seeded customer names and landmarks
    for expected in ["Ramesh", "Sharma", "Ramesh Sharma", "MG Road", "Verma", "Suresh Gowda", "JP Nagar"]:
        assert expected in roster, f"Expected '{expected}' in roster!"

    # Must be deduplicated (case-insensitively)
    lower_terms = [t.lower() for t in roster]
    assert len(lower_terms) == len(set(lower_terms)), "Roster contains duplicate terms!"

    # Must strictly enforce limit
    roster_cap = database.get_keyterm_roster(limit=4)
    assert len(roster_cap) == 4, f"Expected 4 capped terms, got {len(roster_cap)}"

    # Edge cases: 0 or negative limit must return empty list immediately
    assert database.get_keyterm_roster(limit=0) == []
    assert database.get_keyterm_roster(limit=-5) == []

    _ok("get_keyterm_roster returns seeded names, deduplicates, and strictly enforces limit (including 0 cap)")
    passed += 1

    # -------------------------------------------------------------------
    # TEST 4: TTS Disk Cache Transparency (tts_cached boolean)
    # -------------------------------------------------------------------
    _banner("TEST 4: TTS Disk Cache Transparency (tts_cached Boolean)")

    # 1. Direct gnani_service function contract
    res_direct = asyncio.run(
        synthesize_timbre_tts("Namaste! Main VaaniKhata AI assistant hoon.", language_code="hi-IN", bypass_cache=False)
    )
    _info(f"gnani_service tts_cached: {res_direct.get('tts_cached')}")
    assert "tts_cached" in res_direct
    assert isinstance(res_direct["tts_cached"], bool)

    # 2. REST API /api/voice-turn contract (including bypass_cache and ?live=1)
    res_rest = client.post(
        "/api/voice-turn",
        json={"text": "Ramesh Sharma ka total?", "language": "hi-IN"},
    ).json()
    _info(f"REST /api/voice-turn tts_cached: {res_rest.get('tts_cached')}")
    assert "tts_cached" in res_rest
    assert isinstance(res_rest["tts_cached"], bool)

    res_live = client.post(
        "/api/voice-turn?live=1",
        json={"text": "Ramesh Sharma ka total?", "language": "hi-IN", "bypass_cache": True},
    ).json()
    assert "tts_cached" in res_live
    assert res_live["tts_cached"] is False, "Uncached live turn must report tts_cached=False"

    # 3. WebSocket /ws/voice contract (including ?live=1)
    with client.websocket_connect("/ws/voice?session_id=test_cache_ws&live=1") as ws:
        disc = ws.receive_json()
        assert "tts_cached" in disc
        assert disc["tts_cached"] is False, "Turn 1 disclosure with live=1 must report tts_cached=False"

        ws.send_json({"type": "UTTERANCE", "text": "Ramesh Sharma ka total?", "bypass_cache": True})
        v_res = ws.receive_json()
        _info(f"WebSocket VOICE_RESULT tts_cached: {v_res.get('tts_cached')}")
        assert "tts_cached" in v_res
        assert v_res["tts_cached"] is False, "Live turn with bypass_cache must report tts_cached=False"

    _ok("tts_cached boolean & bypass_cache verified across gnani_service, REST, and WebSocket protocols")
    passed += 1

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print(f"\n{Fore.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  {Fore.GREEN}{Style.BRIGHT}SPRINT 1 HARDENING VERIFICATION SUMMARY")
    print(f"{Fore.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  {Fore.GREEN}Passed: {passed}/4 tests completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
