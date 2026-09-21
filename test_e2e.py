import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
import json
import re

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
    print("=== Test 1: Pristine Zero-State on First Boot ===")
    status, body, _ = get("/")
    assert status == 200, f"Expected 200, got {status}"
    assert "Create Your First Trip" in body
    assert "Pristine Empty Ledger" in body
    assert "Load Demo Trip" not in body, "Error: 'Load Demo Trip' found in UI"
    assert "seed_demo_data" not in body
    assert "Goa Vacation (Demo)" not in body
    assert "No trips created yet" in body
    print("[OK] Fresh boot initializes with 0 trips, 0 travelers, and 0 expenses.")
    print("[OK] Verified zero 'Load Demo Trip' buttons in sidebar and zero-state.")

    print("\n=== Test 2: Verify /api/demo Endpoint Is Completely Deleted ===")
    status, body, _ = post("/api/demo")
    assert status == 404 or status == 405, f"Expected 404 or 405, got {status}"
    print(f"[OK] POST /api/demo correctly returned HTTP {status} (route removed).")

    print("\n=== Test 3: Manual Trip Creation & Traveler Onboarding ===")
    status, body, _ = post("/api/trips", {"name": "Kerala Backwaters 2026"})
    assert status == 200
    assert "Kerala Backwaters 2026" in body
    assert "Add Travelers to Kerala Backwaters 2026" in body
    assert "Load Demo Trip" not in body
    print("[OK] Created first trip 'Kerala Backwaters 2026' manually; prompted for travelers.")

    status, body, _ = post("/api/participants", {"name": "Meera"})
    assert status == 200
    status, body, _ = post("/api/participants", {"name": "Karthik"})
    assert status == 200
    assert "Meera" in body
    assert "Karthik" in body
    print("[OK] Added travelers 'Meera' and 'Karthik' manually.")

    print("\n=== Test 4: Expense Logging & Financial Calculations ===")
    status, body, _ = post("/api/expenses", {
        "payer": "Meera",
        "amount": "15000.00",
        "currency": "INR",
        "category": "Lodging",
        "date": "2026-09-21",
        "description": "Houseboat Stay Alleppey",
        "splitters": ["Meera", "Karthik"]
    })
    assert status == 200
    assert "15,000.00" in body
    assert "7,500.00" in body
    print("[OK] Logged INR 15,000.00; fair share calculated at INR 7,500.00.")

    print("\n=== Test 5: Interactive Settlement Checkmark ===")
    status, body, _ = post("/api/settlements/toggle", {
        "from_name": "Karthik",
        "to_name": "Meera"
    })
    assert status == 200
    assert "Settled" in body
    assert "1 of 1 payments marked settled" in body
    print("[OK] Settlement marked as Settled.")

    print("\n=== Test 6: Enforce Pristine Zero-State on Reset ===")
    status, body, _ = post("/api/reset")
    assert status == 200
    assert "Create Your First Trip" in body
    assert "Pristine Empty Ledger" in body
    assert "Load Demo Trip" not in body
    assert "Meera" not in body
    assert "Karthik" not in body
    assert "15,000" not in body

    # Confirm GET / reflects the same clean zero-state
    status, body, _ = get("/")
    assert status == 200
    assert "Create Your First Trip" in body
    assert "No trips created yet" in body
    print("[OK] POST /api/reset cleared all data and cleanly returned to pristine zero-state.")

    print("\n=== Test 7: Universal FX Rates ===")
    status, body, _ = get("/api/fx/rates")
    assert status == 200
    data = json.loads(body)
    assert data["base"] == "INR"
    assert data["rates"]["USD"] == 83.50
    print("[OK] FX rates verified.")

    print("\n========================================================")
    print("ALL CLEAN-STATE AND ZERO-DATA TESTS PASSED WITH 100% SUCCESS!")
    print("========================================================")

if __name__ == "__main__":
    run_tests()
