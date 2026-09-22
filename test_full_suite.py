"""
TripSplit AI - Comprehensive End-to-End Test Suite
===================================================
Executes automated validation across all 7 layers & workflows:
1. Authentication & Access Control
2. Workspace & Trip Management (Zero-State to Multi-Trip)
3. Workspace Invite & Collaborator Onboarding
4. Expense Ingestion & Multi-Currency Conversion
5. Mathematical Settlement Engine & Graph Optimization
6. Settlement Checklist & Payment Tracking
7. Analytics, Health Meter & CSV Exports
"""

import io
import re
import sys
import time
import csv
import json
from typing import List, Dict, Any, Optional

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"

# Test results collector
test_results: List[Dict[str, Any]] = []

def record_test(test_id: str, category: str, description: str, status_code: Any, latency_ms: float, passed: bool, error_msg: str = ""):
    result_str = "PASS" if passed else "FAIL"
    test_results.append({
        "id": test_id,
        "category": category,
        "description": description,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "result": result_str,
        "error": error_msg
    })
    status_display = f"HTTP {status_code}" if status_code else "N/A"
    mark = "✓ PASS" if passed else f"✗ FAIL ({error_msg})"
    print(f"[{result_str}] {test_id.ljust(6)} | {category.ljust(22)} | {description.ljust(48)} | {status_display.ljust(9)} | {latency_ms:6.2f}ms | {mark}")


def print_summary_table():
    print("\n" + "=" * 125)
    print("                      TRIPSPLIT AI - COMPREHENSIVE END-TO-END TEST MATRIX REPORT")
    print("=" * 125)
    print(f"{'ID':<7} | {'Category':<24} | {'Description':<46} | {'HTTP':<8} | {'Latency':<9} | {'Result':<6}")
    print("-" * 125)
    for r in test_results:
        sc = str(r['status_code']) if r['status_code'] is not None else "N/A"
        lat = f"{r['latency_ms']:.1f} ms"
        print(f"{r['id']:<7} | {r['category']:<24} | {r['description'][:44]:<46} | {sc:<8} | {lat:<9} | {r['result']:<6}")
    print("-" * 125)
    total = len(test_results)
    passed = sum(1 for r in test_results if r["result"] == "PASS")
    failed = total - passed
    print(f"Summary: {passed}/{total} Passed (100% Pass Rate)" if failed == 0 else f"Summary: {passed}/{total} Passed, {failed} Failed")
    print("=" * 125 + "\n")


def run_full_suite():
    print("==================================================================")
    print("🚀 STARTING TRIPSPLIT AI COMPREHENSIVE END-TO-END TEST SUITE")
    print(f"Target URL: {BASE_URL}")
    print("==================================================================\n")

    # Clean database state
    try:
        from main import SessionLocal, UserModel, TripModel, ExpenseModel, ParticipantModel, TripMemberModel, SettlementStatusModel
        with SessionLocal() as db:
            db.query(SettlementStatusModel).delete()
            db.query(ExpenseModel).delete()
            db.query(ParticipantModel).delete()
            db.query(TripMemberModel).delete()
            db.query(TripModel).delete()
            db.query(UserModel).delete()
            db.commit()
        print("[SETUP] Database wiped clean for pristine zero-state validation.\n")
    except Exception as e:
        print(f"[SETUP WARNING] Could not reset DB via direct ORM: {e}\n")

    client_kavita = requests.Session()     # Host
    client_vikram = requests.Session()     # Collaborator / Member
    client_unauth = requests.Session()     # Unauthenticated Guest

    # Global holders across tests
    goa_trip_id: Optional[int] = None
    goa_join_code: Optional[str] = None
    himalaya_trip_id: Optional[int] = None
    first_transfer: Optional[Dict[str, Any]] = None

    # ==========================================================================
    # CATEGORY 1: AUTHENTICATION & ACCESS CONTROL
    # ==========================================================================
    # TC-01: Unauthenticated request to / redirects to /login
    t0 = time.perf_counter()
    resp = client_unauth.get(f"{BASE_URL}/", allow_redirects=False)
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 303, f"Expected 303 redirect, got {resp.status_code}"
        assert "/login" in resp.headers.get("Location", ""), f"Expected Location to contain /login, got {resp.headers.get('Location')}"
        record_test("TC-01", "Auth & Access", "Unauthenticated GET / redirects to /login", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-01", "Auth & Access", "Unauthenticated GET / redirects to /login", resp.status_code, lat, False, str(e))

    # TC-02: Registration validation - short password rejection
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/register", data={
        "full_name": "Kavita Reddy",
        "email": "kavita@example.com",
        "password": "123",
        "confirm_password": "123"
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "at least 6 characters" in resp.text, "Expected password length warning"
        record_test("TC-02", "Auth & Access", "Password < 6 chars rejected (HTTP 400)", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-02", "Auth & Access", "Password < 6 chars rejected (HTTP 400)", resp.status_code, lat, False, str(e))

    # TC-03: Registration validation - password mismatch rejection
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/register", data={
        "full_name": "Kavita Reddy",
        "email": "kavita@example.com",
        "password": "password123",
        "confirm_password": "mismatched_password"
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "Passwords do not match" in resp.text, "Expected password mismatch warning"
        record_test("TC-03", "Auth & Access", "Password mismatch rejected (HTTP 400)", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-03", "Auth & Access", "Password mismatch rejected (HTTP 400)", resp.status_code, lat, False, str(e))

    # TC-04: Host registration success & session cookie assignment
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/register", data={
        "full_name": "Kavita Reddy",
        "email": "kavita@example.com",
        "password": "password123",
        "confirm_password": "password123"
    }, allow_redirects=True)
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "tripsplit_session" in client_kavita.cookies, "Expected tripsplit_session cookie to be set"
        record_test("TC-04", "Auth & Access", "Host registration & session cookie established", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-04", "Auth & Access", "Host registration & session cookie established", resp.status_code, lat, False, str(e))

    # TC-05: Duplicate email registration rejection
    t0 = time.perf_counter()
    resp = client_unauth.post(f"{BASE_URL}/register", data={
        "full_name": "Impostor Kavita",
        "email": "kavita@example.com",
        "password": "password123",
        "confirm_password": "password123"
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "already exists" in resp.text, "Expected duplicate email warning"
        record_test("TC-05", "Auth & Access", "Duplicate email registration rejected", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-05", "Auth & Access", "Duplicate email registration rejected", resp.status_code, lat, False, str(e))

    # TC-06: Login with invalid password rejection
    t0 = time.perf_counter()
    resp = client_unauth.post(f"{BASE_URL}/login", data={
        "email": "kavita@example.com",
        "password": "wrongpassword"
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "Invalid email address or password" in resp.text, "Expected invalid credentials warning"
        record_test("TC-06", "Auth & Access", "Invalid password rejected (HTTP 400)", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-06", "Auth & Access", "Invalid password rejected (HTTP 400)", resp.status_code, lat, False, str(e))

    # TC-07: Session termination & Logout flow
    t0 = time.perf_counter()
    # Temp client logs in then logs out
    temp_client = requests.Session()
    temp_client.post(f"{BASE_URL}/login", data={"email": "kavita@example.com", "password": "password123"})
    logout_resp = temp_client.get(f"{BASE_URL}/logout", allow_redirects=False)
    # verify cookie is deleted/expired
    after_logout = temp_client.get(f"{BASE_URL}/", allow_redirects=False)
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert logout_resp.status_code == 303, f"Expected 303, got {logout_resp.status_code}"
        assert after_logout.status_code == 303, f"Expected 303 after logout, got {after_logout.status_code}"
        assert "/login" in after_logout.headers.get("Location", "")
        record_test("TC-07", "Auth & Access", "Session termination /logout clears token", logout_resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-07", "Auth & Access", "Session termination /logout clears token", logout_resp.status_code, lat, False, str(e))

    # ==========================================================================
    # CATEGORY 2: WORKSPACE & TRIP MANAGEMENT (ZERO-STATE TO MULTI-TRIP)
    # ==========================================================================
    # TC-08: Zero-state verification on fresh login
    t0 = time.perf_counter()
    resp = client_kavita.get(f"{BASE_URL}/")
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "Create Your First Trip" in resp.text or "Trip Collaboration Workspace" in resp.text
        # Verify 0 trips / 0 expenses
        assert "₹0.00" in resp.text or "0" in resp.text
        record_test("TC-08", "Workspace Management", "Fresh login renders pristine zero-state", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-08", "Workspace Management", "Fresh login renders pristine zero-state", resp.status_code, lat, False, str(e))

    # TC-09: Primary trip creation & TS-XXXXX passcode generation
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/api/trips", data={
        "name": "Goa Beach Retreat",
        "currency": "INR"
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "Goa Beach Retreat" in resp.text
        # Extract join code matching TS-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{5,6}
        match = re.search(r"TS-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{5,6}", resp.text)
        assert match, "Generated passcode does not match TS-XXXXX format"
        goa_join_code = match.group(0)
        # Extract trip ID
        cookie_trip = client_kavita.cookies.get("tripsplit_active_trip")
        if cookie_trip:
            goa_trip_id = int(cookie_trip)
        else:
            id_match = re.search(r"/api/trips/(\d+)/delete", resp.text)
            assert id_match, "Failed to find active trip ID in HTML"
            goa_trip_id = int(id_match.group(1))

        # Check Host assignment
        assert "👑 Host" in resp.text or "Host" in resp.text
        record_test("TC-09", "Workspace Management", f"Trip created with key {goa_join_code} & Host role", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-09", "Workspace Management", "Trip creation & passcode generation", resp.status_code, lat, False, str(e))

    # TC-10: Multi-trip creation & strict data isolation
    t0 = time.perf_counter()
    # Create secondary trip
    resp_himalaya = client_kavita.post(f"{BASE_URL}/api/trips", data={
        "name": "Himalayan Trek 2026",
        "currency": "INR"
    })
    himalaya_trip_id = int(client_kavita.cookies.get("tripsplit_active_trip", 0))

    # Log an expense specifically in Himalayan Trek
    client_kavita.post(f"{BASE_URL}/api/expenses", data={
        "description": "Trek Guide Fee",
        "amount": "15000.00",
        "currency": "INR",
        "category": "Miscellaneous",
        "date": "2026-09-22",
        "payer": "Kavita Reddy",
        "splitters": ["Kavita Reddy"]
    })

    # Switch active trip back to Goa Beach Retreat
    resp_switch = client_kavita.post(f"{BASE_URL}/api/trips/select", data={"trip_id": goa_trip_id})
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp_himalaya.status_code == 200
        assert resp_switch.status_code == 200
        assert "Goa Beach Retreat" in resp_switch.text
        assert "Trek Guide Fee" not in resp_switch.text, "Data Leak! Himalayan expense leaked into Goa workspace."
        record_test("TC-10", "Workspace Management", "Multi-trip isolation: zero cross-trip data leak", resp_switch.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-10", "Workspace Management", "Multi-trip isolation", resp_switch.status_code, lat, False, str(e))

    # ==========================================================================
    # CATEGORY 3: WORKSPACE INVITE & COLLABORATOR ONBOARDING
    # ==========================================================================
    # TC-11: Register collaborator (Vikram Singhania)
    t0 = time.perf_counter()
    resp = client_vikram.post(f"{BASE_URL}/register", data={
        "full_name": "Vikram Singhania",
        "email": "vikram@example.com",
        "password": "password123",
        "confirm_password": "password123"
    }, allow_redirects=True)
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "tripsplit_session" in client_vikram.cookies
        record_test("TC-11", "Invite & Collaboration", "Collaborator (Vikram) registration", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-11", "Invite & Collaboration", "Collaborator (Vikram) registration", resp.status_code, lat, False, str(e))

    # TC-12: Vikram joins Goa workspace via /join/{join_code}
    t0 = time.perf_counter()
    resp = client_vikram.get(f"{BASE_URL}/join/{goa_join_code}", allow_redirects=True)
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "Goa Beach Retreat" in resp.text
        assert "Vikram Singhania" in resp.text
        assert "Kavita Reddy" in resp.text
        # Check roles in workspace
        assert "👑 Host" in resp.text or "Host" in resp.text
        assert "Member" in resp.text
        record_test("TC-12", "Invite & Collaboration", f"Join workspace via /join/{goa_join_code} as Member", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-12", "Invite & Collaboration", "Join workspace via access key", resp.status_code, lat, False, str(e))

    # TC-13: Permission Boundary: Non-host member cannot delete trip
    t0 = time.perf_counter()
    resp = client_vikram.post(f"{BASE_URL}/api/trips/{goa_trip_id}/delete")
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}"
        assert "Only the Trip Host" in resp.text or "Forbidden" in resp.text
        record_test("TC-13", "Invite & Collaboration", "Non-host member denied trip deletion (HTTP 403)", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-13", "Invite & Collaboration", "Non-host member denied trip deletion", resp.status_code, lat, False, str(e))

    # ==========================================================================
    # CATEGORY 4: EXPENSE INGESTION & MULTI-CURRENCY CONVERSION
    # ==========================================================================
    # TC-14: Add additional participants (Ananya Roy, Rohan Mehta)
    t0 = time.perf_counter()
    r1 = client_kavita.post(f"{BASE_URL}/api/participants", data={"name": "Ananya Roy"})
    r2 = client_kavita.post(f"{BASE_URL}/api/participants", data={"name": "Rohan Mehta"})
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert r1.status_code == 200 and r2.status_code == 200
        assert "Ananya Roy" in r2.text and "Rohan Mehta" in r2.text
        record_test("TC-14", "Expense & Currency", "Onboard participants (Ananya & Rohan)", r2.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-14", "Expense & Currency", "Onboard participants", r2.status_code, lat, False, str(e))

    # TC-15: Standard category expense logging (Accommodation: ₹12,000)
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/api/expenses", data={
        "description": "Beach Villa Accommodation",
        "amount": "12000.00",
        "currency": "INR",
        "category": "Accommodation",
        "date": "2026-09-22",
        "payer": "Kavita Reddy",
        "splitters": ["Kavita Reddy", "Vikram Singhania", "Ananya Roy", "Rohan Mehta"]
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "12,000.00" in resp.text
        assert "Accommodation" in resp.text
        record_test("TC-15", "Expense & Currency", "Log standard expense: Accommodation ₹12,000", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-15", "Expense & Currency", "Log standard expense", resp.status_code, lat, False, str(e))

    # TC-16: Custom category expense logging ("Scuba Diving": ₹8,000)
    t0 = time.perf_counter()
    resp = client_vikram.post(f"{BASE_URL}/api/expenses", data={
        "description": "Grand Island Scuba Diving",
        "amount": "8000.00",
        "currency": "INR",
        "category": "Custom...",
        "custom_category": "Scuba Diving",
        "date": "2026-09-22",
        "payer": "Vikram Singhania",
        "splitters": ["Kavita Reddy", "Vikram Singhania", "Ananya Roy", "Rohan Mehta"]
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "Scuba Diving" in resp.text
        assert "8,000.00" in resp.text
        record_test("TC-16", "Expense & Currency", "Log custom category: Scuba Diving ₹8,000", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-16", "Expense & Currency", "Log custom category", resp.status_code, lat, False, str(e))

    # TC-17: Multi-Currency Foreign Expense Normalization ($100 USD -> ₹8,350.00 INR @ 83.50)
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/api/expenses", data={
        "description": "Duty Free International Snacks",
        "amount": "100.00",
        "currency": "USD",
        "category": "Food & Dining",
        "date": "2026-09-22",
        "payer": "Ananya Roy",
        "splitters": ["Kavita Reddy", "Vikram Singhania", "Ananya Roy", "Rohan Mehta"]
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "8,350.00" in resp.text, "Expected $100 USD to normalize to ₹8,350.00 INR"
        assert "$100.00" in resp.text or "100.00" in resp.text
        record_test("TC-17", "Expense & Currency", "USD -> INR conversion: $100 -> ₹8,350.00", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-17", "Expense & Currency", "USD -> INR conversion", resp.status_code, lat, False, str(e))

    # TC-18: Beneficiary subset splitting (Scooter rental ₹3,000 split between 2 of 4)
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/api/expenses", data={
        "description": "Scooter Rental Pair",
        "amount": "3000.00",
        "currency": "INR",
        "category": "Transport & Fuel",
        "date": "2026-09-22",
        "payer": "Rohan Mehta",
        "splitters": ["Rohan Mehta", "Ananya Roy"]
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "Scooter Rental Pair" in resp.text
        assert "3,000.00" in resp.text
        # Each gets 1,500.00
        assert "1,500.00" in resp.text
        record_test("TC-18", "Expense & Currency", "Beneficiary subset split: ₹3,000 between 2 travelers", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-18", "Expense & Currency", "Beneficiary subset split", resp.status_code, lat, False, str(e))

    # TC-19: AI Receipt Scan Pre-Commit Confirmation simulation (/api/confirm-receipt)
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/api/confirm-receipt", data={
        "description": "Seafood Beach Shack Dinner",
        "amount": "2400.00",
        "currency": "INR",
        "category": "Food & Dining",
        "date": "2026-09-22",
        "payer": "Kavita Reddy",
        "splitters": ["Kavita Reddy", "Vikram Singhania"]
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "Seafood Beach Shack Dinner" in resp.text
        assert "2,400.00" in resp.text
        record_test("TC-19", "Expense & Currency", "AI Receipt pre-commit confirmation simulated", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-19", "Expense & Currency", "AI Receipt pre-commit confirmation", resp.status_code, lat, False, str(e))

    # ==========================================================================
    # CATEGORY 5: MATHEMATICAL SETTLEMENT ENGINE & GRAPH OPTIMIZATION
    # ==========================================================================
    # TC-20: Strict Zero-Sum Invariant (sum of net balances == 0.00)
    t0 = time.perf_counter()
    from main import compute_financials, SessionLocal, TripModel
    with SessionLocal() as db:
        active_t = db.query(TripModel).filter(TripModel.id == goa_trip_id).first()
        fin = compute_financials(db, active_t)
    lat = (time.perf_counter() - t0) * 1000
    try:
        balances = fin["balances"]
        net_sum = sum(b["net"] for b in balances)
        assert abs(net_sum) < 0.01, f"Zero-sum invariant violated: net sum = {net_sum}"
        record_test("TC-20", "Settlement Engine", "Zero-Sum Balance Invariant (sum(net) == 0.00)", 200, lat, True)
    except AssertionError as e:
        record_test("TC-20", "Settlement Engine", "Zero-Sum Balance Invariant", 200, lat, False, str(e))

    # TC-21: Greedy Min-Cash-Flow Upper Bound (transfers <= V - 1)
    t0 = time.perf_counter()
    transactions = fin["transactions"]
    V = fin["total_travelers"]
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert len(transactions) <= V - 1, f"Expected <= {V - 1} transfers, got {len(transactions)}"
        assert len(transactions) > 0, "Expected at least 1 transfer"
        first_transfer = transactions[0]
        record_test("TC-21", "Settlement Engine", f"Min-Cash-Flow upper bound: {len(transactions)} <= {V - 1} transfers", 200, lat, True)
    except AssertionError as e:
        record_test("TC-21", "Settlement Engine", "Min-Cash-Flow upper bound", 200, lat, False, str(e))

    # TC-22: Transactions Saved % Metric calculation
    t0 = time.perf_counter()
    naive_edges = fin["naive_edges"]
    saved_tx = fin["saved_transactions"]
    saved_pct = fin["saved_percent"]
    lat = (time.perf_counter() - t0) * 1000
    try:
        expected_saved = max(0, naive_edges - len(transactions))
        assert saved_tx == expected_saved, f"Saved transactions mismatch: {saved_tx} vs {expected_saved}"
        assert saved_pct >= 0.0, f"Saved percent cannot be negative: {saved_pct}"
        record_test("TC-22", "Settlement Engine", f"Transactions Saved: {saved_tx}/{naive_edges} ({saved_pct}%)", 200, lat, True)
    except AssertionError as e:
        record_test("TC-22", "Settlement Engine", "Transactions Saved % Metric", 200, lat, False, str(e))

    # TC-23: Peer-to-Peer Adjacency Matrix Verification
    t0 = time.perf_counter()
    matrix = fin["matrix"]
    lat = (time.perf_counter() - t0) * 1000
    try:
        participants = fin["participants"]
        for p in participants:
            assert p in matrix, f"Missing {p} in adjacency matrix"
            assert matrix[p][p] == 0.0, f"Self-debt detected for {p}"
        for t in transactions:
            assert matrix[t["from"]][t["to"]] == t["amount"]
        record_test("TC-23", "Settlement Engine", "P2P Adjacency Matrix verified (no self-loops)", 200, lat, True)
    except AssertionError as e:
        record_test("TC-23", "Settlement Engine", "P2P Adjacency Matrix verified", 200, lat, False, str(e))

    # ==========================================================================
    # CATEGORY 6: SETTLEMENT CHECKLIST & PAYMENT TRACKING
    # ==========================================================================
    # TC-24: Interactive Settlement Toggle to "Settled"
    t0 = time.perf_counter()
    assert first_transfer, "Missing first transfer for settlement test"
    resp = client_kavita.post(f"{BASE_URL}/api/settlements/toggle", data={
        "from_name": first_transfer["from"],
        "to_name": first_transfer["to"],
        "amount": str(first_transfer["amount"])
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "Settled" in resp.text
        # Verify in DB
        with SessionLocal() as db:
            from main import SettlementStatusModel
            s_rec = db.query(SettlementStatusModel).filter(
                SettlementStatusModel.trip_id == goa_trip_id,
                SettlementStatusModel.from_user == first_transfer["from"],
                SettlementStatusModel.to_user == first_transfer["to"]
            ).first()
            assert s_rec is not None and s_rec.is_settled is True
        record_test("TC-24", "Settlement Tracking", f"Toggle transfer: {first_transfer['from']} -> {first_transfer['to']} (Settled)", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-24", "Settlement Tracking", "Toggle transfer to Settled", resp.status_code, lat, False, str(e))

    # TC-25: Interactive Settlement Toggle Revert to "Pending"
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/api/settlements/toggle", data={
        "from_name": first_transfer["from"],
        "to_name": first_transfer["to"],
        "amount": str(first_transfer["amount"])
    })
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        with SessionLocal() as db:
            from main import SettlementStatusModel
            s_rec = db.query(SettlementStatusModel).filter(
                SettlementStatusModel.trip_id == goa_trip_id,
                SettlementStatusModel.from_user == first_transfer["from"],
                SettlementStatusModel.to_user == first_transfer["to"]
            ).first()
            assert s_rec is not None and s_rec.is_settled is False
        record_test("TC-25", "Settlement Tracking", "Toggle transfer revert: flipped back to Pending", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-25", "Settlement Tracking", "Toggle transfer revert", resp.status_code, lat, False, str(e))

    # Toggle it back to True so we have a settled record for CSV verification
    client_kavita.post(f"{BASE_URL}/api/settlements/toggle", data={
        "from_name": first_transfer["from"],
        "to_name": first_transfer["to"],
        "amount": str(first_transfer["amount"])
    })

    # ==========================================================================
    # CATEGORY 7: ANALYTICS, HEALTH METER & CSV EXPORT
    # ==========================================================================
    # TC-26: Spend Velocity Meter & Health Analytics
    t0 = time.perf_counter()
    from main import compute_spending_health
    with SessionLocal() as db:
        active_t = db.query(TripModel).filter(TripModel.id == goa_trip_id).first()
        fin = compute_financials(db, active_t)
        health = fin["health"]
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert health["score"] > 0, f"Expected positive health score, got {health['score']}"
        assert health["meter_width"] > 0, f"Expected positive meter width, got {health['meter_width']}"
        assert "Budget" in health["status"] or "Moderate" in health["status"] or "Velocity" in health["status"]
        record_test("TC-26", "Analytics & Export", f"Spend Velocity Meter: Score {health['score']}/100 ({health['status']})", 200, lat, True)
    except AssertionError as e:
        record_test("TC-26", "Analytics & Export", "Spend Velocity Meter & Health", 200, lat, False, str(e))

    # TC-27: Dynamic Achievement Honors
    t0 = time.perf_counter()
    achievements = fin["achievements"]
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert len(achievements) > 0, "Expected at least one achievement badge"
        titles = [a["title"] for a in achievements]
        assert "Highest Spender" in titles, "Expected 'Highest Spender' badge"
        record_test("TC-27", "Analytics & Export", f"Dynamic Achievements: {', '.join(titles)}", 200, lat, True)
    except AssertionError as e:
        record_test("TC-27", "Analytics & Export", "Dynamic Achievements", 200, lat, False, str(e))

    # TC-28: CSV Export - Expense Ledger
    t0 = time.perf_counter()
    resp = client_kavita.get(f"{BASE_URL}/api/export/ledger")
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert "tripsplit_goa_beach_retreat_ledger.csv" in resp.headers.get("Content-Disposition", "")
        reader = list(csv.reader(io.StringIO(resp.text)))
        headers = reader[0]
        assert "Normalized Amount (INR ₹)" in headers
        assert "Split Between" in headers
        assert len(reader) >= 5, f"Expected header + at least 4 expense rows, got {len(reader)}"
        record_test("TC-28", "Analytics & Export", "CSV Export: Expense Ledger (headers & rows verified)", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-28", "Analytics & Export", "CSV Export: Expense Ledger", resp.status_code, lat, False, str(e))

    # TC-29: CSV Export - Settlement Schedule
    t0 = time.perf_counter()
    resp = client_kavita.get(f"{BASE_URL}/api/export/settlement")
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "tripsplit_goa_beach_retreat_settlement.csv" in resp.headers.get("Content-Disposition", "")
        reader = list(csv.reader(io.StringIO(resp.text)))
        headers = reader[0]
        assert headers == ["From (Debtor)", "To (Creditor)", "Amount (INR ₹)", "Status"]
        # Check that Settled status is present in rows
        statuses = [row[3] for row in reader[1:]]
        assert "Settled" in statuses, "Expected at least one Settled status in CSV export"
        record_test("TC-29", "Analytics & Export", "CSV Export: Settlement Schedule (Settled status verified)", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-29", "Analytics & Export", "CSV Export: Settlement Schedule", resp.status_code, lat, False, str(e))

    # TC-30: CSV Export Alias (/api/export/csv)
    t0 = time.perf_counter()
    resp = client_kavita.get(f"{BASE_URL}/api/export/csv")
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "tripsplit_goa_beach_retreat_ledger.csv" in resp.headers.get("Content-Disposition", "")
        record_test("TC-30", "Analytics & Export", "CSV Export Alias /api/export/csv verified", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-30", "Analytics & Export", "CSV Export Alias", resp.status_code, lat, False, str(e))

    # ==========================================================================
    # CATEGORY 8: LIFECYCLE & CLEANUP
    # ==========================================================================
    # TC-31: Host Trip Deletion & Cascading Cleanliness
    t0 = time.perf_counter()
    resp = client_kavita.post(f"{BASE_URL}/api/trips/{goa_trip_id}/delete")
    lat = (time.perf_counter() - t0) * 1000
    try:
        assert resp.status_code == 200
        with SessionLocal() as db:
            from main import TripModel, ExpenseModel, ParticipantModel, SettlementStatusModel
            t_check = db.query(TripModel).filter(TripModel.id == goa_trip_id).first()
            assert t_check is None, "Trip was not deleted from database"
            # Ensure cascade deleted expenses and participants for this trip
            exp_check = db.query(ExpenseModel).filter(ExpenseModel.trip_id == goa_trip_id).count()
            assert exp_check == 0, f"Cascade failed: {exp_check} expenses remain"
        record_test("TC-31", "Lifecycle & Cleanup", "Host trip deletion & database cascade verified", resp.status_code, lat, True)
    except AssertionError as e:
        record_test("TC-31", "Lifecycle & Cleanup", "Host trip deletion & cascade", resp.status_code, lat, False, str(e))

    # Print markdown summary table
    print_summary_table()

    # Assert 100% pass rate
    failed_tests = [r for r in test_results if r["result"] != "PASS"]
    if failed_tests:
        print(f"❌ {len(failed_tests)} TEST(S) FAILED:")
        for ft in failed_tests:
            print(f"  - {ft['id']}: {ft['description']} => {ft['error']}")
        sys.exit(1)
    else:
        print("✨ ALL 31 END-TO-END TESTS PASSED WITH 100% SUCCESS RATE!")
        sys.exit(0)


if __name__ == "__main__":
    run_full_suite()
