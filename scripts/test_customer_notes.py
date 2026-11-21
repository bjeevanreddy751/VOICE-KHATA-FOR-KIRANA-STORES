import urllib.request
import json

def req(path, method="GET", data=None):
    url = f"http://127.0.0.1:8000{path}"
    body = json.dumps(data).encode("utf-8") if data else None
    r = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print("=== Testing Customer Notes & Verification ===")
    
    # 1. Reset demo DB
    reset_res = req("/api/demo/reset", method="POST")
    print("Demo Reset:", reset_res)

    # 2. Check initial seeded notes
    state = req("/api/state")
    print("\n--- Seeded Customer Notes ---")
    for c in state["customers"]:
        print(f"ID {c['id']}: {c['full_name']} | Note: '{c.get('owner_note')}'")
        assert "owner_note" in c

    # 3. Test REST note update
    patch_res = req("/api/customers/1/note", method="PATCH", data={"note": "Tea shop owner - Clears dues every Saturday"})
    print("\n--- REST Note Update ---")
    print("Status:", patch_res["status"])
    print("Updated Note:", patch_res["customer"]["owner_note"])
    assert patch_res["customer"]["owner_note"] == "Tea shop owner - Clears dues every Saturday"

    # 4. Test Voice note update
    voice_res = req("/api/voice-turn", method="POST", data={"text": "Suresh ka note: Daily milk 2 packets at 7am"})
    print("\n--- Voice Note Update ---")
    print("Intent:", voice_res["intent"])
    print("Display:", voice_res["display_reply"])
    print("TTS:", voice_res["tts_reply"])
    print("Highlight ID:", voice_res.get("highlight_customer_id"))
    assert voice_res["intent"] == "CUSTOMER_NOTE_UPDATED"
    assert voice_res.get("highlight_customer_id") is not None

    # 5. Check final state
    state2 = req("/api/state")
    suresh = next(c for c in state2["customers"] if "Suresh" in c["full_name"])
    print(f"\nSuresh note in DB: '{suresh['owner_note']}'")
    assert "Daily milk" in suresh["owner_note"]

    print("\nAll Customer Note checks PASSED cleanly!")

if __name__ == "__main__":
    main()
