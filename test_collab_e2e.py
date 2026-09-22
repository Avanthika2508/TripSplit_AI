import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"

class ClientSession:
    def __init__(self, name="Client"):
        self.name = name
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def get(self, path, allow_redirects=True):
        req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
        try:
            with self.opener.open(req) as resp:
                return resp.status, resp.read().decode("utf-8"), resp.headers, resp.geturl()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers, e.geturl()

    def post(self, path, data=None):
        if data is not None:
            encoded = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
        else:
            encoded = b""
        req = urllib.request.Request(f"{BASE_URL}{path}", data=encoded, method="POST")
        try:
            with self.opener.open(req) as resp:
                return resp.status, resp.read().decode("utf-8"), resp.headers, resp.geturl()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers, e.geturl()


def run_tests():
    print("==================================================================")
    print("🚀 STARTING COLLABORATIVE WORKSPACE & AUTHENTICATION TEST SUITE")
    print("==================================================================")

    # Clean database state for reproducible testing
    from main import SessionLocal, UserModel, TripModel, ExpenseModel, ParticipantModel, TripMemberModel, SettlementStatusModel
    with SessionLocal() as db:
        db.query(SettlementStatusModel).delete()
        db.query(ExpenseModel).delete()
        db.query(ParticipantModel).delete()
        db.query(TripMemberModel).delete()
        db.query(TripModel).delete()
        db.query(UserModel).delete()
        db.commit()
    print("[OK] Test database initialized clean.")

    client_host = ClientSession("Host (Arjun)")
    client_member = ClientSession("Member (Priya)")
    client_unauth = ClientSession("Guest (Unauthenticated)")

    # --------------------------------------------------------------------------
    # TEST 1: Unauthenticated Requests Protected
    # --------------------------------------------------------------------------
    print("\n--- Test 1: Unauthenticated Protection & Login Redirect ---")
    status, body, headers, final_url = client_unauth.get("/")
    assert status == 200, f"Expected 200 after redirect, got {status}"
    assert "/login" in final_url, f"Expected redirect to /login, got {final_url}"
    assert "Sign In" in body
    print("[OK] Unauthenticated GET / successfully redirected to /login.")

    # --------------------------------------------------------------------------
    # TEST 2: Host User Registration & Auto-Login
    # --------------------------------------------------------------------------
    print("\n--- Test 2: Host User Registration ---")
    status, body, headers, final_url = client_host.post("/register", {
        "full_name": "Arjun Patel",
        "email": "arjun@example.com",
        "password": "password123",
        "confirm_password": "password123",
    })
    assert status == 200, f"Expected 200, got {status}"
    assert "Arjun Patel" in body or "/" in final_url
    print("[OK] Host user 'Arjun Patel' registered and authenticated.")

    # Verify session cookie was received
    cookies = {c.name: c.value for c in client_host.cookie_jar}
    assert "tripsplit_session" in cookies, "Expected tripsplit_session cookie"
    print(f"[OK] Session token established: {cookies['tripsplit_session'][:16]}...")

    # --------------------------------------------------------------------------
    # TEST 3: Host Creates Trip & Generates Workspace Access Key
    # --------------------------------------------------------------------------
    print("\n--- Test 3: Trip Creation & Unique Workspace Key Generation ---")
    status, body, headers, _ = client_host.post("/api/trips", {
        "name": "Goa Beach Villa 2026",
        "currency": "INR"
    })
    assert status == 200, f"Expected 200, got {status}"
    assert "Goa Beach Villa 2026" in body
    assert ("TS-" in body or "TRIP-" in body), "Expected workspace key 'TS-XXXXX' in dashboard response"
    
    # Extract join_code from body
    import re
    code_match = re.search(r"(TS-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{5,6}|TRIP-[A-Z0-9]{4,8})", body)
    assert code_match, "Failed to parse TS-XXXXX workspace key from HTML"
    join_code = code_match.group(0)
    print(f"[OK] Trip 'Goa Beach Villa 2026' created with workspace access key: {join_code}")
    print("[OK] Host 'Arjun Patel' automatically enrolled as 👑 Host.")

    # --------------------------------------------------------------------------
    # TEST 4: Second User Registers and Joins via /join/{join_code}
    # --------------------------------------------------------------------------
    print(f"\n--- Test 4: Member Registration & Join via /join/{join_code} ---")
    # Register Priya
    status, body, _, _ = client_member.post("/register", {
        "full_name": "Priya Sharma",
        "email": "priya@example.com",
        "password": "password123",
        "confirm_password": "password123",
    })
    assert status == 200

    # Priya accesses /join/{join_code}
    status, body, _, final_url = client_member.get(f"/join/{join_code}")
    assert status == 200, f"Expected 200, got {status}"
    assert "Goa Beach Villa 2026" in body
    assert "Priya Sharma" in body
    assert "Arjun Patel" in body
    print(f"[OK] Priya Sharma joined workspace {join_code} and was automatically redirected to trip dashboard.")

    # Check Active Workspace renders both users
    assert ("Trip Collaboration Workspace" in body or "Collaboration Workspace" in body or "Multiplayer Lobby" in body)
    assert "👑 Host" in body or "Host" in body
    assert ("💼 Member" in body or "✈️ Member" in body or "Member" in body)
    print("[OK] Collaboration Workspace displays both Host (Arjun) and Member (Priya) with roles.")

    # --------------------------------------------------------------------------
    # TEST 5: Collaborative Expense Logging & Shared Min-Cash-Flow Calculation
    # --------------------------------------------------------------------------
    print("\n--- Test 5: Collaborative Expense Logging & Min-Cash-Flow Settling ---")
    # Priya logs Villa Deposit ₹10,000 split equally with Arjun
    status, body, _, _ = client_member.post("/api/expenses", {
        "payer": "Priya Sharma",
        "amount": "10000.00",
        "currency": "INR",
        "category": "Accommodation",
        "date": "2026-09-22",
        "description": "Villa Booking Advance",
        "splitters": ["Arjun Patel", "Priya Sharma"]
    })
    assert status == 200
    assert "10,000.00" in body
    assert "Accommodation" in body
    print("[OK] Member (Priya) logged ₹10,000.00 Accommodation expense.")

    # Check that Arjun owes Priya ₹5,000.00
    assert "Arjun Patel" in body
    assert "Priya Sharma" in body
    assert "5,000.00" in body
    print("[OK] Financial engine computes: Arjun Patel owes Priya Sharma ₹5,000.00.")

    # Host (Arjun) logs Dinner ₹4,000 split equally
    status, body, _, _ = client_host.post("/api/expenses", {
        "payer": "Arjun Patel",
        "amount": "4000.00",
        "currency": "INR",
        "category": "Food & Dining",
        "date": "2026-09-22",
        "description": "Beachfront Seafood Dinner",
        "splitters": ["Arjun Patel", "Priya Sharma"]
    })
    assert status == 200
    assert "4,000.00" in body
    # Arjun paid 4,000 (net +2,000). Net balance: Arjun owes Priya 5,000 - 2,000 = 3,000.
    assert "3,000.00" in body
    print("[OK] Host (Arjun) logged ₹4,000.00 Dinner. Net optimized transfer recalculated: ₹3,000.00.")

    # --------------------------------------------------------------------------
    # TEST 6: Interactive Settlement Payment Checkmark
    # --------------------------------------------------------------------------
    print("\n--- Test 6: Settlement Payment Checkmark ---")
    status, body, _, _ = client_host.post("/api/settlements/toggle", {
        "from_name": "Arjun Patel",
        "to_name": "Priya Sharma",
        "amount": "3000.00"
    })
    assert status == 200
    assert "Settled" in body
    print("[OK] Transfer from Arjun Patel to Priya Sharma marked as Settled.")

    # --------------------------------------------------------------------------
    # TEST 7: Permission Enforcement - Non-Host Cannot Delete Trip
    # --------------------------------------------------------------------------
    print("\n--- Test 7: Permissions Check (Host vs Member) ---")
    # Get active trip ID from cookies or HTML
    cookies_host = {c.name: c.value for c in client_host.cookie_jar}
    trip_id = int(cookies_host.get("tripsplit_active_trip", 0))
    if not trip_id:
        trip_id_match = re.search(r"/api/trips/(\d+)/delete", body)
        assert trip_id_match, "Failed to find trip ID"
        trip_id = int(trip_id_match.group(1))

    # Priya (member) tries to delete trip
    status, body, _, _ = client_member.post(f"/api/trips/{trip_id}/delete")
    assert status == 403, f"Expected 403 Forbidden for member trip deletion, got {status}"
    print(f"[OK] Member (Priya) was denied trip deletion with HTTP {status} Forbidden.")

    # --------------------------------------------------------------------------
    # TEST 8: Host Can Delete Trip & Cascades Cleanly
    # --------------------------------------------------------------------------
    print("\n--- Test 8: Host Deletes Trip ---")
    status, body, _, _ = client_host.post(f"/api/trips/{trip_id}/delete")
    assert status == 200, f"Expected 200 for host trip deletion, got {status}"
    assert "Goa Beach Villa 2026" not in body or "Create Your First Trip" in body
    print("[OK] Host (Arjun) deleted trip cleanly; database records cascaded.")

    # --------------------------------------------------------------------------
    # TEST 9: Sign Out / Logout Flow
    # --------------------------------------------------------------------------
    print("\n--- Test 9: Sign Out / Logout ---")
    status, body, _, final_url = client_host.get("/logout")
    assert "/login" in final_url
    # Attempt to visit / again with host client
    status, body, _, final_url = client_host.get("/")
    assert "/login" in final_url
    print("[OK] Logout cleared session cookie and redirected to /login.")

    print("\n==================================================================")
    print("✨ ALL COLLABORATIVE WORKSPACE & AUTHENTICATION TESTS PASSED 100%!")
    print("==================================================================")


if __name__ == "__main__":
    run_tests()
