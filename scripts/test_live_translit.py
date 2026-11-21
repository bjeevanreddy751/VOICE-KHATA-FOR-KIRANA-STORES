import os
from backend.database import init_db
from backend.ledger_engine import process_utterance, SessionState

# Reset db
init_db()

session = SessionState()

print("--- Turn 1: Indic Script Multi-Entry ---")
res1 = process_utterance("रमेश का 340 उधार कल 200 दिया था।", session)
print("Turn 1 Intent:", res1["intent"])
print("Turn 1 Display:", res1["display_reply"])
print("Turn 1 TTS:", res1["tts_reply"])
print("Turn 1 Detected Lang:", res1["detected_language"])
assert res1["intent"] == "HOMONYM_CLARIFICATION_REQUIRED", f"Turn 1 failed: {res1['intent']}"

print("\n--- Turn 2: Disambiguation (Sharma) ---")
res2 = process_utterance("शर्मा", session)
print("Turn 2 Intent:", res2["intent"])
print("Turn 2 Display:", res2["display_reply"])
print("Turn 2 TTS:", res2["tts_reply"])
assert res2["intent"] == "DISAMBIGUATION_RESOLVED", f"Turn 2 failed: {res2['intent']}"
assert "140" in res2["display_reply"], f"Turn 2 expected 140, got: {res2['display_reply']}"

print("\n--- Turn 3: Atomic Correction (नहीं 430 कर दो) ---")
res3 = process_utterance("नहीं 430 कर दो", session)
print("Turn 3 Intent:", res3["intent"])
print("Turn 3 Display:", res3["display_reply"])
print("Turn 3 TTS:", res3["tts_reply"])
assert res3["intent"] == "ATOMIC_CORRECTION", f"Turn 3 failed: {res3['intent']}"
assert "230" in res3["display_reply"], f"Turn 3 expected 230, got: {res3['display_reply']}"

print("\n✅ ALL 3 TURNS PASSED PERFECTLY!")
