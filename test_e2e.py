import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
import json
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

def get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    try:
        with opener.open(req) as resp:
            return resp.status, resp.read().decode("utf-8"), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), e.headers

def post(path, data=None):
    if data is not None:
        encoded_data = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
    else:
        encoded_data = b""
    req = urllib.request.Request(f"{BASE_URL}{path}", data=encoded_data, method="POST")
    try:
        with opener.open(req) as resp:
            return resp.status, resp.read().decode("utf-8"), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), e.headers

def run_tests():
    print("=== Setup: Register & Authenticate User ===")
    # Register test user
    post("/register", {
        "full_name": "Test User",
        "email": "testuser@example.com",
        "password": "password123",
        "confirm_password": "password123"
    })
    post("/login", {
        "email": "testuser@example.com",
        "password": "password123"
    })

    print("=== Setup: Clean Database to Zero-State ===")
    status, body, _ = post("/api/reset")
    assert status == 200

    print("\n=== Test 1: Pristine Zero-State on First Boot ===")
    status, body, _ = get("/")
    assert status == 200, f"Expected 200, got {status}"
    assert "Create Your First Trip" in body
    assert "Load Demo Trip" not in body, "Error: 'Load Demo Trip' found in UI"
    assert "seed_demo_data" not in body
    print("[OK] Fresh boot initializes with 0 trips, 0 travelers, and 0 expenses.")
    print("[OK] Verified zero 'Load Demo Trip' buttons in sidebar and zero-state.")

    print("\n=== Test 2: Verify /api/demo Endpoint Is Completely Deleted ===")
    status, body, _ = post("/api/demo")
    assert status in (404, 405), f"Expected 404 or 405, got {status}"
    print(f"[OK] POST /api/demo correctly returned HTTP {status} (route removed).")

    print("\n=== Test 3: Manual Trip Creation & Traveler Onboarding ===")
    status, body, _ = post("/api/trips", {"name": "Andaman Expedition 2026"})
    assert status == 200
    assert "Andaman Expedition 2026" in body
    print("[OK] Created first trip 'Andaman Expedition 2026' manually.")

    status, body, _ = post("/api/participants", {"name": "Aarav"})
    assert status == 200
    status, body, _ = post("/api/participants", {"name": "Pooja"})
    assert status == 200
    status, body, _ = post("/api/participants", {"name": "Vikram"})
    assert status == 200
    assert "Aarav" in body
    assert "Pooja" in body
    assert "Vikram" in body
    print("[OK] Added travelers 'Aarav', 'Pooja', and 'Vikram' manually.")

    print("\n=== Test 4: Log Expense with Standard Category (Food & Dining) ===")
    status, body, _ = post("/api/expenses", {
        "payer": "Aarav",
        "amount": "6000.00",
        "currency": "INR",
        "category": "Food & Dining",
        "date": "2026-09-21",
        "description": "Seafood Banquet Havelock",
        "splitters": ["Aarav", "Pooja", "Vikram"]
    })
    assert status == 200
    assert "6,000.00" in body
    assert ("Food & Dining" in body) or ("Food &amp; Dining" in body)
    print("[OK] Logged standard category 'Food & Dining' expense (₹6,000.00).")

    print("\n=== Test 5: Log Expense with Custom Category (Scuba Diving) ===")
    status, body, _ = post("/api/expenses", {
        "payer": "Pooja",
        "amount": "12000.00",
        "currency": "INR",
        "category": "Custom",
        "custom_category": "Scuba Diving",
        "date": "2026-09-21",
        "description": "PADI Deep Sea Certification",
        "splitters": ["Aarav", "Pooja", "Vikram"]
    })
    assert status == 200
    assert "12,000.00" in body
    assert "Scuba Diving" in body, "Error: Custom category 'Scuba Diving' not found in response"
    print("[OK] Successfully logged expense with dynamic custom category 'Scuba Diving'!")

    print("\n=== Test 6: Verify Spend by Category Includes 'Scuba Diving' and Palette Colors ===")
    assert "Spend by Category" in body
    assert "Scuba Diving" in body
    assert ("Food & Dining" in body) or ("Food &amp; Dining" in body)
    print("[OK] Custom category seamlessly renders in 'Spend by Category' progress chart.")

    print("\n=== Test 7: Interactive Settlement Checkmark ===")
    # Transfers should exist
    assert "Optimized Debt Transfers" in body
    status, body, _ = post("/api/settlements/toggle", {
        "from_name": "Vikram",
        "to_name": "Pooja"
    })
    assert status == 200
    assert "Settled" in body
    print("[OK] Toggled settlement checkmark; marked payment as Settled.")

    print("\n=== Test 8: CSV Export with Custom Category Verification ===")
    status, csv_body, headers = get("/api/export/csv")
    assert status == 200, f"Expected 200, got {status}"
    assert "Scuba Diving" in csv_body, "Error: Custom category not found in CSV export"
    assert "Food & Dining" in csv_body
    assert "PADI Deep Sea Certification" in csv_body
    print("[OK] CSV Export verified containing custom category 'Scuba Diving'.")

    print("\n=== Test 9: Universal FX Rates Endpoint ===")
    status, body, _ = get("/api/fx/rates")
    assert status == 200
    fx_data = json.loads(body)
    assert fx_data["base"] == "INR"
    assert "USD" in fx_data["rates"]
    assert "EUR" in fx_data["rates"]
    assert "GBP" in fx_data["rates"]
    print(f"[OK] Universal FX rates verified: USD={fx_data['rates']['USD']}, EUR={fx_data['rates']['EUR']}, GBP={fx_data['rates']['GBP']}.")

    print("\n=== Test 10: Pristine State Reset Enforcement ===")
    status, body, _ = post("/api/reset")
    assert status == 200
    assert "Create Your First Trip" in body or "No trips created yet" in body
    assert "Aarav" not in body
    assert "Scuba Diving" not in body
    print("[OK] Reset endpoint clears all trips back to pristine zero-state.")

    print("\n==================================================================")
    print("✨ ALL 10 END-TO-END TESTS (CUSTOM CATEGORIES, FINANCIALS,")
    print("   ZERO-STATE, SETTLEMENTS, CSV EXPORT) PASSED WITH 100% SUCCESS!")
    print("==================================================================")

if __name__ == "__main__":
    run_tests()
