"""
Playwright automated test suite for Serial Number Automation web app.
Covers: Auth (lockout/unlock/redirect/logout), RBAC, Dashboard,
       Sessions list (search/filter/row-click), Session detail,
       Serials list (sort/filter/search/toggle AJAX), Export,
       User management (validation), Settings, CSRF, Page jumpers.

Run:
    pytest tests/test_app.py --headed --slowmo 200          # visible + slow
    pytest tests/test_app.py -x -v                           # fast, stop on first fail
    pytest tests/test_app.py -x -v -k test_auth              # run a single class
"""

import re
import csv
import io
import time
import pytest
from playwright.sync_api import Page, expect
from conftest import BASE_URL, ADMIN_USER, ADMIN_PASS

LOCKOUT_LIMIT = 5


def login(page: Page, username: str = ADMIN_USER, password: str = ADMIN_PASS):
    page.goto(f"{BASE_URL}/login")
    page.fill("input[name='username']", username)
    page.fill("input[name='password']", password)
    with page.expect_navigation():
        page.click("button[type='submit']")


def get_csrf(page: Page) -> str:
    return page.locator("meta[name='csrf-token']").get_attribute("content")


def logout(page: Page):
    with page.expect_navigation():
        page.locator("button:has-text('Sign out')").click()


class TestAuth:
    def test_login_success(self, page: Page):
        login(page)
        expect(page).to_have_url(f"{BASE_URL}/")
        expect(page.locator("h1:has-text('Dashboard')")).to_be_visible()
        logout(page)

    def test_login_bad_password_shows_error(self, page: Page):
        page.goto(f"{BASE_URL}/login")
        page.fill("input[name='username']", ADMIN_USER)
        page.fill("input[name='password']", "badpass")
        page.click("button[type='submit']")
        page.wait_for_timeout(500)
        expect(page.locator("text=Invalid")).to_be_visible()
        expect(page).to_have_url(f"{BASE_URL}/login")

    def test_login_lockout(self, page: Page):
        page.goto(f"{BASE_URL}/login")
        for i in range(LOCKOUT_LIMIT):
            page.fill("input[name='username']", ADMIN_USER)
            page.fill("input[name='password']", f"wrong{i}")
            page.click("button[type='submit']")
            page.wait_for_timeout(300)
        expect(page.locator("text=locked").first).to_be_visible(timeout=5000)

    def test_login_next_redirect(self, page: Page):
        page.goto(f"{BASE_URL}/settings")
        page.wait_for_url(f"{BASE_URL}/login**")
        expect(page.locator("input[name='next']")).to_have_value("/settings")
        page.fill("input[name='username']", ADMIN_USER)
        page.fill("input[name='password']", ADMIN_PASS)
        with page.expect_navigation():
            page.click("button[type='submit']")
        page.wait_for_url(f"{BASE_URL}/settings**")
        expect(page.locator("h1:has-text('Settings')")).to_be_visible()
        logout(page)

    def test_logout(self, page: Page):
        login(page)
        logout(page)
        expect(page).to_have_url(f"{BASE_URL}/login")

    def test_access_after_logout_redirects_to_login(self, page: Page):
        page.goto(f"{BASE_URL}/login")
        page.fill("input[name='username']", ADMIN_USER)
        page.fill("input[name='password']", ADMIN_PASS)
        with page.expect_navigation():
            page.click("button[type='submit']")
        page.wait_for_url(f"{BASE_URL}/")
        with page.expect_navigation():
            page.locator("text=Sign out").click()
        page.wait_for_url(f"{BASE_URL}/login")
        page.goto(f"{BASE_URL}/serials")
        page.wait_for_url(f"{BASE_URL}/login**")


class TestRBAC:
    def test_view_only_cannot_see_settings(self, page: Page):
        login(page, "viewuser", "ViewUser123!")
        expect(page.locator("a[href='/settings']")).not_to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_view_only_cannot_post_bulk_edit(self, page: Page):
        login(page, "viewuser", "ViewUser123!")
        page.goto(f"{BASE_URL}/serials")
        csrf = get_csrf(page)
        resp = page.request.post(
            f"{BASE_URL}/serials/bulk-status",
            data={"status": "used", "ranges": [], "serials": []},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status == 403
        page.goto(f"{BASE_URL}/login")

    def test_view_actions_can_see_settings(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        expect(page.locator("a[href='/settings']")).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_admin_can_see_users(self, page: Page):
        login(page)
        expect(page.locator("a[href='/users']")).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_view_actions_cannot_see_users(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        expect(page.locator("a[href='/users']")).not_to_be_visible()
        page.goto(f"{BASE_URL}/login")


class TestDashboard:
    def test_dashboard_loads(self, page: Page):
        login(page)
        expect(page.locator("h1:has-text('Dashboard')")).to_be_visible()
        expect(page.locator("text=Sessions").first).to_be_visible()
        expect(page.locator("text=Current Counter").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_dashboard_shows_stats(self, page: Page):
        login(page)
        for label in ["Total", "Confirmed", "Partial", "Issued", "Voided"]:
            expect(page.locator(f"text={label}").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")


class TestSessionsList:
    def test_sessions_page_loads(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        expect(page.locator("h1:has-text('Print Sessions')")).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_sessions_search(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        page.fill("input[name='search']", "test")
        page.locator("button:has-text('Search')").click()
        page.wait_for_timeout(500)
        expect(page).to_have_url(re.compile(r"/sessions.*search=test"))
        page.goto(f"{BASE_URL}/login")

    def test_sessions_filter_buttons_exist(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        for status in ["All", "Issued", "Confirmed", "Partial", "Voided"]:
            expect(page.locator(f"button:has-text('{status}')").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_sessions_row_click_navigates_to_detail(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        page.wait_for_timeout(500)
        row = page.locator("table tbody tr[onclick]").first
        if row.is_visible():
            onclick = row.get_attribute("onclick")
            match = re.search(r"/sessions/(\d+)", onclick)
            assert match, f"Could not find session_id in onclick: {onclick}"
            session_id = match.group(1)
            row.click()
            page.wait_for_url(f"{BASE_URL}/sessions/{session_id}")
            expect(page.locator(f"text=Session #{session_id}").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_sessions_page_jumper_present(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        jumper = page.locator("#sessionsPageJumper")
        expect(jumper).to_be_visible()
        assert jumper.get_attribute("data-max") is not None
        page.goto(f"{BASE_URL}/login")

    def test_sessions_page_jumper_out_of_range_shows_red(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        jumper = page.locator("#sessionsPageJumper")
        max_page = int(jumper.get_attribute("data-max") or "1")
        jumper.fill(str(max_page + 999))
        jumper.press("Enter")
        page.wait_for_timeout(1000)
        assert f"{BASE_URL}/sessions" in page.url
        border_class = jumper.get_attribute("class") or ""
        assert "border-red" in border_class, f"Expected red border, got class: {border_class}"
        page.goto(f"{BASE_URL}/login")


class TestSessionDetail:
    def test_session_detail_loads_known_session(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        page.wait_for_timeout(500)
        row = page.locator("table tbody tr[onclick]").first
        if row.is_visible():
            onclick = row.get_attribute("onclick")
            match = re.search(r"/sessions/(\d+)", onclick)
            if match:
                session_id = match.group(1)
                row.click()
                page.wait_for_url(f"{BASE_URL}/sessions/{session_id}")
                expect(page.locator(f"text=Session #{session_id}").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_session_detail_has_page_jumper(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/sessions")
        page.wait_for_timeout(500)
        row = page.locator("table tbody tr[onclick]").first
        if row.is_visible():
            onclick = row.get_attribute("onclick")
            match = re.search(r"/sessions/(\d+)", onclick)
            if match:
                row.click()
                page.wait_for_url(f"{BASE_URL}/sessions/**")
                jumper = page.locator("#detailPageJumper")
                if jumper.is_visible():
                    assert jumper.get_attribute("data-max") is not None
        page.goto(f"{BASE_URL}/login")


class TestSerialsList:
    def test_serials_page_loads(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials")
        expect(page.locator("h1:has-text('Serial Numbers')")).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_serials_sort_toggle(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials")
        page.locator("a[href*='sort=asc']").first.click()
        page.wait_for_url(f"{BASE_URL}/serials**")
        assert "sort=asc" in page.url
        page.goto(f"{BASE_URL}/login")

    def test_serials_filter_buttons(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials")
        for status in ["All", "Used", "Unused"]:
            expect(page.locator(f"button:has-text('{status}')").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_serials_search(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials")
        page.fill("input[name='search']", "100")
        page.locator("button:has-text('Search')").click()
        page.wait_for_url(f"{BASE_URL}/serials?**search=100**")
        page.goto(f"{BASE_URL}/login")

    def test_serials_toggle_status(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials")
        page.wait_for_timeout(500)
        toggle_btn = page.locator("tbody button:has-text('Used'), tbody button:has-text('Unused')").first
        if toggle_btn.is_visible():
            current_text = toggle_btn.text_content().strip()
            toggle_btn.click()
            page.wait_for_timeout(1500)
            new_text = toggle_btn.text_content().strip()
            assert new_text != current_text, f"Status should have changed: {current_text} -> {new_text}"
        page.goto(f"{BASE_URL}/login")

    def test_serials_page_jumper_present(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials")
        jumper = page.locator("#serialsPageJumper")
        expect(jumper).to_be_visible()
        assert jumper.get_attribute("data-max") is not None
        page.goto(f"{BASE_URL}/login")

    def test_serials_export_modal_opens(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials")
        page.wait_for_timeout(500)
        export_btn = page.locator("button:has-text('Export CSV')")
        if export_btn.is_visible():
            export_btn.click()
            page.wait_for_timeout(300)
            expect(page.locator("#exportModal")).to_be_visible()
            expect(page.locator("#exportStart")).to_be_visible()
            expect(page.locator("#exportEnd")).to_be_visible()
        page.goto(f"{BASE_URL}/login")


class TestExport:
    def test_export_form_loads(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/export")
        expect(page.locator("text=Export CSV").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_export_csv_has_header(self, page: Page):
        login(page)
        resp = page.request.get(
            f"{BASE_URL}/export/download",
            params={"start_serial": 1000, "end_serial": 1002},
        )
        assert resp.status == 200
        content = resp.text()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) >= 1
        assert rows[0] == ["SerialNumber", "RandomNumber"], f"Unexpected header: {rows[0]}"
        page.goto(f"{BASE_URL}/login")

    def test_export_csv_known_range(self, page: Page):
        login(page)
        resp = page.request.get(
            f"{BASE_URL}/export/download",
            params={"start_serial": 1, "end_serial": 500},
        )
        assert resp.status == 200
        content = resp.text()
        reader = csv.reader(io.StringIO(content))
        header = next(reader)
        assert header == ["SerialNumber", "RandomNumber"]
        data_rows = list(reader)
        for row in data_rows:
            assert len(row) == 2
            assert row[0].isdigit()
        page.goto(f"{BASE_URL}/login")


class TestSettings:
    def test_settings_page_loads(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        page.goto(f"{BASE_URL}/settings")
        expect(page.locator("h1:has-text('Settings')").first).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_settings_empty_path_error(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        page.goto(f"{BASE_URL}/settings")
        path_input = page.locator("input[name='path']")
        if path_input.is_visible():
            path_input.fill("")
            with page.expect_navigation():
                page.locator("form[action$='/lbl-path'] button[type='submit']").click()
            page.wait_for_timeout(500)
            expect(page.locator("text=empty").or_(page.locator("text=cannot")).first).to_be_visible(timeout=3000)
        page.goto(f"{BASE_URL}/login")

    def test_settings_non_lbl_path_error(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        page.goto(f"{BASE_URL}/settings")
        path_input = page.locator("input[name='path']")
        if path_input.is_visible():
            path_input.fill("C:\\test.txt")
            with page.expect_navigation():
                page.locator("form[action$='/lbl-path'] button[type='submit']").click()
            page.wait_for_timeout(500)
            expect(page.locator("text=.lbl").first).to_be_visible(timeout=3000)
        page.goto(f"{BASE_URL}/login")

    def test_settings_nonexistent_file_error(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        page.goto(f"{BASE_URL}/settings")
        path_input = page.locator("input[name='path']")
        if path_input.is_visible():
            path_input.fill("C:\\nonexistent_file.lbl")
            with page.expect_navigation():
                page.locator("form[action$='/lbl-path'] button[type='submit']").click()
            page.wait_for_timeout(500)
            expect(page.locator("text=not found").or_(page.locator("text=not exist")).first).to_be_visible(timeout=3000)
        page.goto(f"{BASE_URL}/login")


class TestUserManagement:
    def test_users_page_loads_for_admin(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/users")
        expect(page.locator("h1:has-text('Users')")).to_be_visible()
        page.goto(f"{BASE_URL}/login")

    def test_create_user_duplicate_username(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/users")
        page.locator("button:has-text('Add User')").click()
        page.wait_for_timeout(300)
        page.locator("#modalUsername").fill(ADMIN_USER)
        page.locator("#modalPassword").fill("NewUser123!")
        page.locator("#modalRole").select_option("view_only")
        page.locator("#userForm button[type='submit']").click()
        page.wait_for_timeout(500)
        expect(page.locator("text=already exists").or_(page.locator("text=already taken")).first).to_be_visible(timeout=5000)
        page.goto(f"{BASE_URL}/login")

    def test_create_user_short_password(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/users")
        page.locator("button:has-text('Add User')").click()
        page.wait_for_timeout(300)
        page.locator("#modalUsername").fill("newtestuser")
        page.locator("#modalPassword").fill("123")
        page.locator("#userForm button[type='submit']").click()
        page.wait_for_timeout(500)
        expect(page.locator("text=8 characters").first).to_be_visible(timeout=3000)
        page.goto(f"{BASE_URL}/login")

    def test_create_user_empty_username(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/users")
        page.locator("button:has-text('Add User')").click()
        page.wait_for_timeout(300)
        page.locator("#modalUsername").fill("")
        page.locator("#modalPassword").fill("ValidPass123!")
        page.evaluate("document.getElementById('modalUsername').removeAttribute('required')")
        page.locator("#userForm button[type='submit']").click()
        page.wait_for_timeout(500)
        expect(page.locator("text=cannot be empty").or_(page.locator("text=required")).first).to_be_visible(timeout=3000)
        page.goto(f"{BASE_URL}/login")

    def test_create_user_success_and_cleanup(self, page: Page):
        test_username = f"testuser_{int(time.time())}"
        login(page)
        page.goto(f"{BASE_URL}/users")
        page.locator("button:has-text('Add User')").click()
        page.wait_for_timeout(300)
        page.locator("#modalUsername").fill(test_username)
        page.locator("#modalPassword").fill("TestUser123!")
        page.locator("#modalRole").select_option("view_only")
        with page.expect_navigation():
            page.locator("#userForm button[type='submit']").click()
        assert page.url.startswith(f"{BASE_URL}/users")
        expect(page.locator(f"text={test_username}").first).to_be_visible(timeout=3000)

        delete_btn = page.locator(f"tr:has-text('{test_username}') button:has-text('Delete')")
        if delete_btn.is_visible():
            delete_btn.click()
            page.wait_for_timeout(300)
            with page.expect_navigation():
                page.locator("#deleteForm button[type='submit']").click()
            assert page.url.startswith(f"{BASE_URL}/users")
        page.goto(f"{BASE_URL}/login")


class TestCSRF:
    def test_login_without_csrf_still_works(self, page: Page):
        page.goto(f"{BASE_URL}/login")
        page.evaluate("document.querySelector('input[name=\"_csrf\"]')?.remove();")
        page.fill("input[name='username']", ADMIN_USER)
        page.fill("input[name='password']", ADMIN_PASS)
        with page.expect_navigation():
            page.click("button[type='submit']")
        expect(page).to_have_url(f"{BASE_URL}/")
        page.goto(f"{BASE_URL}/login")

    def test_post_without_csrf_returns_403(self, page: Page):
        login(page)
        resp = page.request.post(
            f"{BASE_URL}/serials/bulk-status",
            data={"status": "used", "ranges": [], "serials": []},
            headers={"X-CSRF-Token": "invalid-token"},
        )
        assert resp.status == 403
        page.goto(f"{BASE_URL}/login")

    def test_logout_has_csrf(self, page: Page):
        login(page)
        csrf_input = page.locator("form[action='/logout'] input[name='_csrf']").first
        expect(csrf_input).to_be_attached()
        assert csrf_input.get_attribute("value") != ""
        page.goto(f"{BASE_URL}/login")


class TestPrintSession:
    def test_print_start_form_submit_with_expect_navigation(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        page.goto(f"{BASE_URL}/print")
        page.wait_for_timeout(500)
        start_form = page.locator("form[action*='/print']").first
        if start_form.is_visible():
            with page.expect_navigation():
                page.evaluate("document.querySelector('form[action*=\"/print\"]').submit()")
            assert page.url.startswith(f"{BASE_URL}/print")
        else:
            pytest.skip("Start form not visible — counter may not be initialized")
        page.goto(f"{BASE_URL}/login")

    def test_print_confirm_form_submit_with_expect_navigation(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        page.goto(f"{BASE_URL}/print/start")
        page.wait_for_timeout(500)
        form = page.locator("form[action*='/print']").first
        if form.is_visible():
            with page.expect_navigation():
                page.evaluate("document.querySelector('form[action*=\"/print\"]').submit()")
            assert page.url.startswith(f"{BASE_URL}/print")
        page.goto(f"{BASE_URL}/login")


class TestUserIDRegex:
    def test_open_edit_modal_has_quoted_args(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/users")
        page.wait_for_timeout(500)
        edit_buttons = page.locator("button:has-text('Edit')")
        count = edit_buttons.count()
        assert count > 0
        for i in range(count):
            btn = edit_buttons.nth(i)
            onclick = btn.get_attribute("onclick")
            match = re.search(r"openEditModal\('(\d+)'", onclick)
            assert match, f"Fix failed: openEditModal should have quoted user_id. Got: {onclick}"
            assert match.group(1).isdigit()
        page.goto(f"{BASE_URL}/login")


class TestExportInvestigation:
    def test_export_range_1000_1002_data_exists(self, page: Page):
        login(page)
        resp = page.request.get(
            f"{BASE_URL}/export/download",
            params={"start_serial": 1000, "end_serial": 1002},
        )
        assert resp.status == 200
        content = resp.text()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        print(f"\n[INVESTIGATION] Export 1000-1002: {len(rows)} row(s) incl header")
        print(f"[INVESTIGATION] Header: {rows[0] if rows else 'EMPTY'}")
        if len(rows) > 1:
            print(f"[INVESTIGATION] Data rows: {rows[1:]}")
        else:
            print("[INVESTIGATION] No data rows — session_rows may not be populated")
        assert rows[0] == ["SerialNumber", "RandomNumber"]
        page.goto(f"{BASE_URL}/login")

    def test_check_session_rows_via_serials_page(self, page: Page):
        login(page)
        page.goto(f"{BASE_URL}/serials?search=1000&page=1")
        page.wait_for_timeout(500)
        tbody = page.locator("table tbody")
        text = tbody.text_content() if tbody.is_visible() else ""
        print(f"\n[INVESTIGATION] Serials search '1000': {text.strip()[:200] or 'No results'}")
        page.goto(f"{BASE_URL}/login")


class TestPrintSessionFlow:
    def test_print_start_page_loads(self, page: Page):
        login(page, "actuser", "ActionUser123!")
        page.goto(f"{BASE_URL}/print")
        page.wait_for_timeout(300)
        expect(
            page.locator("text=Start Printing Session").first
            .or_(page.locator("text=First-time Setup").first)
        ).to_be_visible()
        page.goto(f"{BASE_URL}/login")