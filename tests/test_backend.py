"""
Backend integration tests via FastAPI TestClient (no browser required).
Covers: auth logic, CSRF enforcement, RBAC, user-management validation,
        serials bulk-status validation, export, sessions listing, and
        miscellaneous HTTP concerns (404, security headers).

Requires: MySQL running with the serial_tracker database.
Does NOT require a live web server — TestClient starts the app in-process.

Run:
    pytest tests/test_backend.py -v
    pytest tests/test_backend.py -v -k TestRBAC
"""

import re
import time
import pytest
from fastapi.testclient import TestClient

from web_app.app import app
from web_app.auth import hash_password, verify_password, ROLE_LEVELS

ADMIN_USER = "admin"
ADMIN_PASS = "admin1234"

# Backend-specific test users created/torn down by the module fixture.
# Using a leading underscore prefix to distinguish from the Playwright test users.
_VIEW_USER = "_btview"
_VIEW_PASS = "BtView1234!"
_ACT_USER  = "_btact"
_ACT_PASS  = "BtAct1234!"
_ACT_USER2 = "_btact2"   # second view_actions user for "blocked" scenario tests
_ACT_PASS2 = "BtAct21234!"


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _csrf(text: str) -> str:
    """Pull CSRF token from rendered HTML (meta tag or hidden input)."""
    for pat in (
        r'name="csrf-token"[^>]*content="([0-9a-f]{64})"',
        r'name="_csrf"[^>]*value="([0-9a-f]{64})"',
    ):
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""


def _login(client: TestClient, username: str = ADMIN_USER, password: str = ADMIN_PASS) -> str:
    """Log in and return the active CSRF token.

    GET /login seeds the session (and csrf_token) before the POST so the
    token is valid for subsequent CSRF-protected endpoints.
    """
    r = client.get("/login")
    csrf = _csrf(r.text)
    r2 = client.post(
        "/login",
        data={"username": username, "password": password, "next": "/"},
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303), f"Login failed ({r2.status_code}) for {username}"
    return csrf


def _admin_csrf(client: TestClient) -> str:
    """Log in as admin and return the CSRF token."""
    return _login(client, ADMIN_USER, ADMIN_PASS)


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Single TestClient for the whole module; starts the app once."""
    with TestClient(app, raise_server_exceptions=True) as c:
        # Create backend test users via the /users/create endpoint.
        csrf = _admin_csrf(c)
        for username, password, role in (
            (_VIEW_USER,  _VIEW_PASS,  "view_only"),
            (_ACT_USER,   _ACT_PASS,   "view_actions"),
            (_ACT_USER2,  _ACT_PASS2,  "view_actions"),
        ):
            c.post(
                "/users/create",
                data={"username": username, "password": password, "role": role, "_csrf": csrf},
                follow_redirects=False,
            )
        c.cookies.clear()

        yield c

        # Teardown — delete the backend test users.
        c.cookies.clear()
        csrf = _admin_csrf(c)
        r = c.get("/users")
        for username in (_VIEW_USER, _ACT_USER, _ACT_USER2):
            m = re.search(r"openEditModal\('(\d+)',\s*'" + re.escape(username) + r"'", r.text)
            if m:
                c.post(
                    f"/users/{m.group(1)}/delete",
                    data={"_csrf": csrf},
                    follow_redirects=False,
                )


@pytest.fixture(autouse=True)
def fresh_session(client):
    """Clear session cookies before and after every test."""
    client.cookies.clear()
    yield
    client.cookies.clear()


# ---------------------------------------------------------------------------
# Unit tests — auth.py (no DB, no HTTP)
# ---------------------------------------------------------------------------

class TestAuthFunctions:
    def test_hash_and_verify_roundtrip(self):
        pw = "s3cur3P@ss!"
        assert verify_password(pw, hash_password(pw))

    def test_wrong_password_rejected(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_hash_is_not_plaintext(self):
        pw = "plaintext"
        assert hash_password(pw) != pw

    def test_two_hashes_of_same_password_differ(self):
        pw = "same"
        # bcrypt uses a random salt so two hashes of the same pw must differ
        assert hash_password(pw) != hash_password(pw)

    def test_role_levels_ordering(self):
        assert ROLE_LEVELS["view_only"] < ROLE_LEVELS["view_actions"] < ROLE_LEVELS["admin"]

    def test_unknown_role_not_in_levels(self):
        assert "superuser" not in ROLE_LEVELS


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

class TestLoginRoute:
    def test_login_page_returns_200(self, client):
        r = client.get("/login")
        assert r.status_code == 200

    def test_login_success_redirects_to_root(self, client):
        client.get("/login")
        r = client.post(
            "/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS, "next": "/"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.headers["location"] == "/"

    def test_login_next_param_honored(self, client):
        client.get("/login")
        r = client.post(
            "/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS, "next": "/sessions"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/sessions"

    def test_login_unsafe_next_falls_back_to_root(self, client):
        client.get("/login")
        r = client.post(
            "/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS, "next": "http://evil.com"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/"

    def test_login_bad_password_returns_401(self, client):
        client.get("/login")
        r = client.post(
            "/login",
            data={"username": ADMIN_USER, "password": "notthepassword", "next": "/"},
        )
        assert r.status_code == 401
        assert "Invalid" in r.text

    def test_login_unknown_user_returns_401(self, client):
        client.get("/login")
        r = client.post(
            "/login",
            data={"username": "nobody", "password": "anything", "next": "/"},
        )
        assert r.status_code == 401

    def test_login_lockout_after_5_bad_attempts(self, client):
        client.get("/login")
        r = None
        for _ in range(5):
            r = client.post("/login", data={"username": ADMIN_USER, "password": "bad"})
        # The 5th failed attempt is the one that triggers the lockout message
        assert "locked" in r.text.lower()

    def test_locked_out_user_cannot_login_with_correct_password(self, client):
        client.get("/login")
        for _ in range(5):
            client.post("/login", data={"username": ADMIN_USER, "password": "bad"})
        r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert r.status_code == 429
        assert "too many" in r.text.lower()

    def test_already_logged_in_redirects_away_from_login(self, client):
        _login(client)
        r = client.get("/login", follow_redirects=False)
        assert r.status_code == 302

    def test_logout_clears_session(self, client):
        csrf = _login(client)
        r = client.post("/logout", data={"_csrf": csrf}, follow_redirects=False)
        assert r.status_code in (302, 303)
        # After logout, protected pages redirect to /login again
        r2 = client.get("/", follow_redirects=False)
        assert r2.status_code == 302
        assert "/login" in r2.headers["location"]

    def test_login_without_csrf_still_works(self, client):
        # /login POST is intentionally CSRF-exempt
        r = client.post(
            "/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS, "next": "/"},
            follow_redirects=False,
        )
        assert r.status_code == 302


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

class TestUnauthenticatedAccess:
    PROTECTED = ["/", "/sessions", "/serials", "/export", "/print", "/users", "/settings"]

    def test_protected_routes_redirect_to_login(self, client):
        for path in self.PROTECTED:
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 302, f"{path} returned {r.status_code}"
            assert "/login" in r.headers["location"], f"{path} didn't redirect to /login"

    def test_login_redirect_carries_next_param(self, client):
        r = client.get("/settings", follow_redirects=False)
        assert "next=/settings" in r.headers["location"]


# ---------------------------------------------------------------------------
# CSRF enforcement
# ---------------------------------------------------------------------------

class TestCSRF:
    def test_post_with_bad_csrf_header_returns_403(self, client):
        _login(client)
        r = client.post(
            "/serials/bulk-status",
            json={"status": "used", "ranges": [{"start": 1, "end": 1}], "serials": []},
            headers={"X-CSRF-Token": "invalid-token"},
        )
        assert r.status_code == 403

    def test_post_with_missing_csrf_returns_403(self, client):
        _login(client)
        r = client.post(
            "/logout",
            data={},  # no _csrf field
            follow_redirects=False,
        )
        assert r.status_code == 403

    def test_post_with_correct_csrf_header_passes(self, client):
        csrf = _login(client)
        r = client.post(
            "/serials/bulk-status",
            json={"status": "used", "ranges": [{"start": 999999999, "end": 999999999}], "serials": []},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code != 403

    def test_logout_requires_csrf(self, client):
        _login(client)
        r = client.post("/logout", data={"_csrf": "bad"}, follow_redirects=False)
        assert r.status_code == 403

    def test_logout_with_valid_csrf_succeeds(self, client):
        csrf = _login(client)
        r = client.post("/logout", data={"_csrf": csrf}, follow_redirects=False)
        assert r.status_code in (302, 303)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

class TestRBAC:
    def test_view_only_cannot_get_settings(self, client):
        _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.get("/settings", follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_view_only_cannot_get_users(self, client):
        _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.get("/users", follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_view_only_cannot_post_bulk_status(self, client):
        csrf = _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.post(
            "/serials/bulk-status",
            json={"status": "used", "ranges": [], "serials": [1]},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code in (302, 403)

    def test_view_only_cannot_get_print(self, client):
        _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.get("/print", follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_view_only_can_get_dashboard(self, client):
        _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.get("/")
        assert r.status_code == 200

    def test_view_only_can_get_serials(self, client):
        _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.get("/serials")
        assert r.status_code == 200

    def test_view_only_can_get_sessions(self, client):
        _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.get("/sessions")
        assert r.status_code == 200

    def test_view_only_can_get_export_form(self, client):
        _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.get("/export")
        assert r.status_code == 200

    def test_view_actions_can_get_settings(self, client):
        _login(client, _ACT_USER, _ACT_PASS)
        r = client.get("/settings")
        assert r.status_code == 200

    def test_view_actions_can_get_print(self, client):
        _login(client, _ACT_USER, _ACT_PASS)
        r = client.get("/print")
        assert r.status_code == 200

    def test_view_actions_cannot_get_users(self, client):
        _login(client, _ACT_USER, _ACT_PASS)
        r = client.get("/users", follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_admin_can_get_users(self, client):
        _login(client)
        r = client.get("/users")
        assert r.status_code == 200

    def test_admin_can_get_all_pages(self, client):
        _login(client)
        for path in ["/", "/sessions", "/serials", "/export", "/settings", "/users"]:
            r = client.get(path)
            assert r.status_code == 200, f"{path} returned {r.status_code}"


# ---------------------------------------------------------------------------
# User management — server-side validation
# ---------------------------------------------------------------------------

class TestUserManagement:
    def _create(self, client, csrf, username, password="ValidPass1!", role="view_only"):
        return client.post(
            "/users/create",
            data={"username": username, "password": password, "role": role, "_csrf": csrf},
            follow_redirects=False,
        )

    def test_create_empty_username_rejected(self, client):
        csrf = _admin_csrf(client)
        # Use whitespace-only: pydantic accepts it as a non-empty str, but
        # the route does `username.strip()` and rejects it as blank.
        r = self._create(client, csrf, "   ")
        assert r.status_code == 303
        assert "error" in r.headers["location"]

    def test_create_short_password_rejected(self, client):
        csrf = _admin_csrf(client)
        r = self._create(client, csrf, "newuser_x1", password="short")
        assert r.status_code == 303
        assert "error" in r.headers["location"]

    def test_create_invalid_role_rejected(self, client):
        csrf = _admin_csrf(client)
        r = self._create(client, csrf, "newuser_x2", role="superuser")
        assert r.status_code == 303
        assert "error" in r.headers["location"]

    def test_create_duplicate_username_rejected(self, client):
        csrf = _admin_csrf(client)
        r = self._create(client, csrf, ADMIN_USER)
        assert r.status_code == 303
        assert "error" in r.headers["location"]

    def test_create_success_redirects_to_users(self, client):
        username = f"_bttmp_{int(time.time())}"
        csrf = _admin_csrf(client)
        r = self._create(client, csrf, username, password="TmpPass1234!")
        assert r.status_code == 303
        assert "error" not in r.headers["location"]
        # Cleanup
        r2 = client.get("/users")
        m = re.search(r"openEditModal\('(\d+)',\s*'" + re.escape(username) + r"'", r2.text)
        if m:
            client.post(f"/users/{m.group(1)}/delete", data={"_csrf": csrf}, follow_redirects=False)

    def test_cannot_delete_own_account(self, client):
        csrf = _admin_csrf(client)
        r = client.get("/users")
        m = re.search(r"openEditModal\('(\d+)',\s*'" + re.escape(ADMIN_USER) + r"'", r.text)
        assert m, "Could not find admin's user_id in /users page"
        uid = m.group(1)
        r2 = client.post(f"/users/{uid}/delete", data={"_csrf": csrf}, follow_redirects=False)
        assert r2.status_code == 303
        assert "error" in r2.headers["location"]

    def test_cannot_delete_last_admin(self, client):
        # admin is the only admin; deleting it must be blocked
        # (same as deleting own account check — covered above, but test the "last admin" path)
        csrf = _admin_csrf(client)
        r = client.get("/users")
        m = re.search(r"openEditModal\('(\d+)',\s*'" + re.escape(ADMIN_USER) + r"'", r.text)
        if m:
            uid = m.group(1)
            r2 = client.post(f"/users/{uid}/delete", data={"_csrf": csrf}, follow_redirects=False)
            assert "error" in r2.headers["location"]

    def test_non_admin_cannot_create_user(self, client):
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r = self._create(client, csrf, "shouldnotwork")
        # view_actions can't reach /users/create → 302 to login or 403
        assert r.status_code in (302, 403)

    def test_edit_user_empty_username_rejected(self, client):
        csrf = _admin_csrf(client)
        r = client.get("/users")
        m = re.search(r"openEditModal\('(\d+)',\s*'" + re.escape(_VIEW_USER) + r"'", r.text)
        assert m, f"Could not find {_VIEW_USER} in /users page"
        uid = m.group(1)
        r2 = client.post(
            f"/users/{uid}/edit",
            data={"username": "   ", "role": "view_only", "password": "", "_csrf": csrf},
            follow_redirects=False,
        )
        assert r2.status_code == 303
        assert "error" in r2.headers["location"]

    def test_edit_user_duplicate_username_rejected(self, client):
        csrf = _admin_csrf(client)
        r = client.get("/users")
        m = re.search(r"openEditModal\('(\d+)',\s*'" + re.escape(_VIEW_USER) + r"'", r.text)
        assert m
        uid = m.group(1)
        r2 = client.post(
            f"/users/{uid}/edit",
            data={"username": ADMIN_USER, "role": "view_only", "password": "", "_csrf": csrf},
            follow_redirects=False,
        )
        assert r2.status_code == 303
        assert "error" in r2.headers["location"]


# ---------------------------------------------------------------------------
# Serials bulk-status — request body validation
# ---------------------------------------------------------------------------

class TestSerialsBulkStatus:
    def _post(self, client, csrf, body):
        return client.post(
            "/serials/bulk-status",
            json=body,
            headers={"X-CSRF-Token": csrf},
        )

    def test_invalid_status_returns_400(self, client):
        csrf = _admin_csrf(client)
        r = self._post(client, csrf, {"status": "deleted", "ranges": [], "serials": [1]})
        assert r.status_code == 400
        assert r.json()["ok"] is False

    def test_empty_ranges_and_serials_returns_400(self, client):
        csrf = _admin_csrf(client)
        r = self._post(client, csrf, {"status": "used", "ranges": [], "serials": []})
        assert r.status_code == 400

    def test_range_start_greater_than_end_returns_400(self, client):
        csrf = _admin_csrf(client)
        r = self._post(client, csrf, {"status": "used", "ranges": [{"start": 100, "end": 50}], "serials": []})
        assert r.status_code == 400

    def test_non_integer_serial_returns_400(self, client):
        csrf = _admin_csrf(client)
        r = self._post(client, csrf, {"status": "used", "ranges": [], "serials": ["abc"]})
        assert r.status_code == 400

    def test_valid_serial_range_returns_ok(self, client):
        csrf = _admin_csrf(client)
        # Use a serial number that definitely doesn't exist — 0 affected is fine
        r = self._post(client, csrf, {"status": "used", "ranges": [{"start": 999999900, "end": 999999901}], "serials": []})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "affected" in data

    def test_valid_serials_list_returns_ok(self, client):
        csrf = _admin_csrf(client)
        r = self._post(client, csrf, {"status": "unused", "ranges": [], "serials": [999999900, 999999901]})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_view_only_gets_403(self, client):
        csrf = _login(client, _VIEW_USER, _VIEW_PASS)
        r = self._post(client, csrf, {"status": "used", "ranges": [{"start": 1, "end": 1}], "serials": []})
        assert r.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Export routes
# ---------------------------------------------------------------------------

class TestExport:
    def test_export_form_loads(self, client):
        _login(client)
        r = client.get("/export")
        assert r.status_code == 200
        assert "Export CSV" in r.text

    def test_export_download_csv_header(self, client):
        _login(client)
        r = client.get("/export/download", params={"start_serial": 1, "end_serial": 10})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "SerialNumber" in r.text
        assert "RandomNumber" in r.text

    def test_export_download_start_gt_end_redirects(self, client):
        _login(client)
        r = client.get(
            "/export/download",
            params={"start_serial": 100, "end_serial": 50},
            follow_redirects=False,
        )
        # RedirectResponse without explicit status_code defaults to 307
        assert r.status_code in (302, 303, 307)

    def test_export_download_range_too_large_redirects(self, client):
        _login(client)
        r = client.get(
            "/export/download",
            params={"start_serial": 1, "end_serial": 20000},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303, 307)

    def test_serials_export_range_too_large_redirects(self, client):
        _login(client)
        r = client.get(
            "/serials/export",
            params={"start_serial": 1, "end_serial": 20000},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303)

    def test_export_unauthenticated_redirects(self, client):
        r = client.get("/export/download", params={"start_serial": 1, "end_serial": 10},
                       follow_redirects=False)
        assert r.status_code == 302


# ---------------------------------------------------------------------------
# Sessions list
# ---------------------------------------------------------------------------

class TestSessionsListRoute:
    def test_page_loads(self, client):
        _login(client)
        r = client.get("/sessions")
        assert r.status_code == 200
        assert "Print Sessions" in r.text

    def test_sort_asc(self, client):
        _login(client)
        r = client.get("/sessions", params={"sort": "asc"})
        assert r.status_code == 200

    def test_sort_desc(self, client):
        _login(client)
        r = client.get("/sessions", params={"sort": "desc"})
        assert r.status_code == 200

    def test_invalid_sort_is_sanitised(self, client):
        _login(client)
        r = client.get("/sessions", params={"sort": "DROP TABLE"})
        assert r.status_code == 200  # must not crash

    def test_search_param(self, client):
        _login(client)
        r = client.get("/sessions", params={"search": "test", "sort": "desc"})
        assert r.status_code == 200

    def test_status_filter_issued(self, client):
        _login(client)
        r = client.get("/sessions", params={"status_filter": "issued"})
        assert r.status_code == 200

    def test_status_filter_invalid_ignored(self, client):
        _login(client)
        r = client.get("/sessions", params={"status_filter": "bad_value"})
        assert r.status_code == 200

    def test_page_param_below_1_clamped(self, client):
        _login(client)
        r = client.get("/sessions", params={"page": "-5"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

class TestMisc:
    def test_unknown_route_returns_404(self, client):
        _login(client)
        r = client.get("/this-page-does-not-exist")
        assert r.status_code == 404

    def test_security_header_nosniff(self, client):
        r = client.get("/login")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_security_header_no_frame(self, client):
        r = client.get("/login")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_security_header_referrer_policy(self, client):
        r = client.get("/login")
        assert r.headers.get("Referrer-Policy") == "same-origin"

    def test_dashboard_loads_for_admin(self, client):
        _login(client)
        r = client.get("/")
        assert r.status_code == 200
        assert "Dashboard" in r.text

    def test_serials_page_loads(self, client):
        _login(client)
        r = client.get("/serials")
        assert r.status_code == 200
        assert "Serial Numbers" in r.text

    def test_settings_page_loads_for_admin(self, client):
        _login(client)
        r = client.get("/settings")
        assert r.status_code == 200
        assert "Settings" in r.text

    def test_csrf_token_in_login_form(self, client):
        r = client.get("/login")
        # get_csrf_token global dep must set a token visible in the form
        assert _csrf(r.text) != "", "CSRF token missing from login page"

    def test_csrf_token_stable_across_requests_same_session(self, client):
        r1 = client.get("/login")
        tok1 = _csrf(r1.text)
        r2 = client.get("/login")
        tok2 = _csrf(r2.text)
        assert tok1 == tok2 == tok2, "CSRF token changed within the same session"


# ---------------------------------------------------------------------------
# Print session flow — single and multi-session scenarios
# ---------------------------------------------------------------------------

class TestPrintSessionFlow:
    """
    Tests for the print session lifecycle and concurrent-session blocking.

    Design notes:
    - Each test that creates a session cleans it up in a try/finally block.
    - _cleanup() is used when the session might be owned by a different user
      than the one currently logged in — it re-logs in as admin (who owns all
      sessions via the _owns() check) and voids whatever is active.
    - seed values (start_serial / start_random) are always supplied so tests
      work whether or not the counter was previously initialised.
    """

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _start(client, csrf, qty=5, mo="TEST-MO"):
        """POST /print/start with seed values so it works on a fresh counter."""
        return client.post(
            "/print/start",
            data={
                "qty": qty,
                "mo_number": mo,
                "start_serial": "100000",
                "start_random": "500000",
                "_csrf": csrf,
            },
            follow_redirects=False,
        )

    @staticmethod
    def _sid(response) -> str:
        """Extract session_id string from a /print/confirm/{id} Location header."""
        return response.headers.get("location", "").rstrip("/").split("/")[-1]

    @staticmethod
    def _void(client, csrf, session_id):
        return client.post(
            f"/print/void/{session_id}",
            data={"_csrf": csrf},
            follow_redirects=False,
        )

    @staticmethod
    def _cleanup(client):
        """Void any active session as admin (admin owns every session)."""
        client.cookies.clear()
        csrf = _login(client)
        r = client.get("/print", follow_redirects=False)
        if r.status_code == 303 and "/print/confirm/" in r.headers.get("location", ""):
            sid = r.headers["location"].rstrip("/").split("/")[-1]
            client.post(f"/print/void/{sid}", data={"_csrf": csrf}, follow_redirects=False)
        client.cookies.clear()

    # ------------------------------------------------------------------ single-session basics

    def test_start_session_redirects_to_confirm(self, client):
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r = self._start(client, csrf)
        sid = self._sid(r)
        try:
            assert r.status_code == 303
            assert "/print/confirm/" in r.headers["location"]
            assert sid.isdigit()
        finally:
            if sid.isdigit():
                self._void(client, csrf, sid)

    def test_confirm_page_loads_for_session_owner(self, client):
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r = self._start(client, csrf, mo="CONFIRM-LOAD")
        sid = self._sid(r)
        try:
            r2 = client.get(f"/print/confirm/{sid}")
            assert r2.status_code == 200
            assert f"Session #{sid}" in r2.text or sid in r2.text
        finally:
            self._void(client, csrf, sid)

    def test_invalid_session_id_redirects_to_print(self, client):
        _login(client, _ACT_USER, _ACT_PASS)
        r = client.get("/print/confirm/999999999", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/print"

    # ------------------------------------------------------------------ same-user duplicate start

    def test_same_user_second_start_redirects_to_existing_session(self, client):
        """Starting a second session as the same user must return the existing one."""
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf, mo="FIRST-MO")
        sid = self._sid(r1)
        try:
            assert "/print/confirm/" in r1.headers["location"]
            r2 = self._start(client, csrf, mo="SECOND-MO")
            assert r2.status_code == 303
            # Must point to the same session, not a newly created one
            assert r2.headers["location"] == r1.headers["location"]
        finally:
            self._void(client, csrf, sid)

    # ------------------------------------------------------------------ cross-user blocking

    def test_second_user_blocked_while_session_active(self, client):
        """A non-owning user hitting /print/start must be redirected to /print."""
        csrf1 = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf1, mo="USER1-MO")
        sid = self._sid(r1)
        try:
            assert "/print/confirm/" in r1.headers["location"]

            client.cookies.clear()
            csrf2 = _login(client, _ACT_USER2, _ACT_PASS2)
            r2 = self._start(client, csrf2, mo="USER2-MO")

            # Non-owner is redirected to /print (shows locked state), not to a confirm page
            assert r2.status_code == 303
            assert r2.headers["location"] == "/print"
        finally:
            self._cleanup(client)

    def test_second_user_get_print_shows_locked(self, client):
        """GET /print for a non-owner while a session is active returns 200 (locked view)."""
        csrf1 = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf1, mo="LOCKED-VIEW")
        try:
            client.cookies.clear()
            _login(client, _ACT_USER2, _ACT_PASS2)
            r2 = client.get("/print")
            assert r2.status_code == 200
            # The page must mention the lock (owner's username visible in template)
            assert _ACT_USER in r2.text or "locked" in r2.text.lower() or "in progress" in r2.text.lower()
        finally:
            self._cleanup(client)

    def test_admin_can_access_any_confirm_page(self, client):
        """Admin owns all sessions so it can view any confirm page."""
        csrf_act = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf_act, mo="ADMIN-VIEW")
        sid = self._sid(r1)
        try:
            client.cookies.clear()
            _login(client)  # admin
            r2 = client.get(f"/print/confirm/{sid}")
            assert r2.status_code == 200
        finally:
            self._cleanup(client)

    # ------------------------------------------------------------------ post-void / post-complete

    def test_void_session_allows_new_session(self, client):
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf, mo="VOID-FIRST")
        sid1 = self._sid(r1)
        assert "/print/confirm/" in r1.headers["location"]

        rv = self._void(client, csrf, sid1)
        assert rv.status_code == 303

        # Counter may or may not exist after void; start again with seed values
        r2 = self._start(client, csrf, mo="VOID-SECOND")
        sid2 = self._sid(r2)
        try:
            assert r2.status_code == 303
            assert "/print/confirm/" in r2.headers["location"]
            assert sid2 != sid1
        finally:
            self._void(client, csrf, sid2)

    def test_complete_session_allows_new_session(self, client):
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf, qty=2, mo="COMPLETE-FIRST")
        sid1 = self._sid(r1)
        assert "/print/confirm/" in r1.headers["location"]

        rc = client.post(f"/print/complete/{sid1}", data={"_csrf": csrf}, follow_redirects=False)
        assert rc.status_code == 303

        r2 = self._start(client, csrf, mo="COMPLETE-SECOND")
        sid2 = self._sid(r2)
        try:
            assert r2.status_code == 303
            assert "/print/confirm/" in r2.headers["location"]
            assert sid2 != sid1
        finally:
            self._void(client, csrf, sid2)

    def test_incomplete_within_range_creates_partial_status(self, client):
        """POST /print/incomplete with a serial inside the range must 303 to /print."""
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf, qty=5, mo="PARTIAL-MO")
        sid = self._sid(r1)
        assert "/print/confirm/" in r1.headers["location"]

        # Extract the actual serial_range_start from the confirm page so this test
        # is not sensitive to whatever counter value preceded it.
        confirm = client.get(f"/print/confirm/{sid}")
        m = re.search(r'name="last_good_serial"[^>]*min="(\d+)"', confirm.text)
        if not m:
            self._void(client, csrf, sid)
            pytest.skip("Could not extract serial_range_start from confirm page")
        range_start = int(m.group(1))

        r2 = client.post(
            f"/print/incomplete/{sid}",
            data={"last_good_serial": str(range_start), "_csrf": csrf},
            follow_redirects=False,
        )
        assert r2.status_code == 303
        assert r2.headers["location"] == "/print"

    def test_incomplete_outside_range_shows_error(self, client):
        """POST /print/incomplete with a serial outside the range must redirect with error."""
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r1 = self._start(client, csrf, qty=5, mo="OUT-OF-RANGE")
        sid = self._sid(r1)
        try:
            r2 = client.post(
                f"/print/incomplete/{sid}",
                data={"last_good_serial": "1", "_csrf": csrf},  # way below range start
                follow_redirects=False,
            )
            assert r2.status_code == 303
            assert "error" in r2.headers["location"].lower()
        finally:
            # Session still issued if incomplete failed — void it
            self._void(client, csrf, sid)

    # ------------------------------------------------------------------ input validation

    def test_qty_zero_rejected(self, client):
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r = client.post("/print/start", data={
            "qty": 0, "mo_number": "TEST",
            "start_serial": "100000", "start_random": "500000",
            "_csrf": csrf,
        }, follow_redirects=False)
        assert r.status_code == 303
        assert "error" in r.headers["location"].lower()

    def test_qty_exceeds_15000_rejected(self, client):
        csrf = _login(client, _ACT_USER, _ACT_PASS)
        r = client.post("/print/start", data={
            "qty": 16000, "mo_number": "TEST",
            "start_serial": "100000", "start_random": "500000",
            "_csrf": csrf,
        }, follow_redirects=False)
        assert r.status_code == 303
        assert "error" in r.headers["location"].lower()

    def test_view_only_cannot_start_session(self, client):
        csrf = _login(client, _VIEW_USER, _VIEW_PASS)
        r = client.post("/print/start", data={
            "qty": 5, "mo_number": "TEST",
            "start_serial": "100000", "start_random": "500000",
            "_csrf": csrf,
        }, follow_redirects=False)
        assert r.status_code in (302, 303, 403)
