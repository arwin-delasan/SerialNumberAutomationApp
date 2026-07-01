import pytest
from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://localhost:8000"
ADMIN_USER = "admin"
ADMIN_PASS = "admin1234"

TEST_USERS = [
    {"username": "viewuser", "password": "ViewUser123!", "role": "view_only"},
    {"username": "actuser",  "password": "ActionUser123!", "role": "view_actions"},
]


def _admin_page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    page.goto(f"{BASE_URL}/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    with page.expect_navigation():
        page.click("button[type='submit']")
    return browser, context, page


def _server_is_up() -> bool:
    import socket
    try:
        with socket.create_connection(("localhost", 8000), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def ensure_test_users():
    """Create test users before the session; delete only the ones we created after.
    Skips silently if the external server isn't reachable (e.g. when running
    only the backend TestClient tests without a live server).
    """
    if not _server_is_up():
        yield
        return

    created = []

    # Setup — open and close playwright before yielding so the loop is free for tests
    with sync_playwright() as p:
        browser, context, page = _admin_page(p)
        for u in TEST_USERS:
            page.goto(f"{BASE_URL}/users")
            page.wait_for_timeout(300)
            if page.locator(f"td:text-is('{u['username']}')").count() == 0:
                page.locator("button:has-text('Add User')").click()
                page.wait_for_timeout(300)
                page.locator("#modalUsername").fill(u["username"])
                page.locator("#modalPassword").fill(u["password"])
                page.locator("#modalRole").select_option(u["role"])
                page.locator("#userForm button[type='submit']").click()
                page.wait_for_timeout(500)
                created.append(u["username"])
        context.close()
        browser.close()

    yield

    # Teardown — separate playwright instance, only deletes what we created
    if not created:
        return
    with sync_playwright() as p:
        browser, context, page = _admin_page(p)
        for username in created:
            page.goto(f"{BASE_URL}/users")
            page.wait_for_timeout(300)
            delete_btn = page.locator(f"tr:has-text('{username}') button:has-text('Delete')")
            if delete_btn.is_visible():
                delete_btn.click()
                page.wait_for_timeout(300)
                page.locator("#deleteForm button[type='submit']").click()
                page.wait_for_timeout(500)
        context.close()
        browser.close()


@pytest.fixture(scope="function")
def page():
    """Provide a fresh Playwright page for each test."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        page_instance = context.new_page()
        yield page_instance
        context.close()
        browser.close()
