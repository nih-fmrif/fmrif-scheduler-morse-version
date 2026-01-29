"""
Playwright end-to-end test for OAuth 2.0 PKCE flow with Microsoft Entra.

This test validates the full authentication flow:
1. Load login page
2. Click "Login with NIH Credentials" button
3. Authenticate with Microsoft Entra
4. Return to application dashboard

Requirements:
- Valid test credentials must be in .env as OAUTH_TEST_USERNAME and OAUTH_TEST_PASSWORD
- Application must be accessible at STAGING_URL
- This test only runs if both conditions are met

Usage:
    pytest tests/playwright/test_oauth_flow.py -v --headed  # Run with browser window
    pytest tests/playwright/test_oauth_flow.py -v           # Run headless
"""

import os
import pytest
from playwright.sync_api import sync_playwright, expect


# Configuration from environment
STAGING_URL = os.getenv(
    "STAGING_URL", "https://fmrif-schedule-backend-staging.nimh.nih.gov"
)
OAUTH_TEST_USERNAME = os.getenv("OAUTH_TEST_USERNAME", "")
OAUTH_TEST_PASSWORD = os.getenv("OAUTH_TEST_PASSWORD", "")


def skip_if_no_credentials():
    """Skip test if credentials not configured."""
    if not OAUTH_TEST_USERNAME or not OAUTH_TEST_PASSWORD:
        pytest.skip(
            "OAuth test credentials not found in .env (OAUTH_TEST_USERNAME, OAUTH_TEST_PASSWORD)"
        )


@pytest.fixture
def browser():
    """Provide a Playwright browser instance."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """Provide a Playwright page instance."""
    context = browser.new_context()
    page = context.new_page()
    # Ignore HTTPS certificate errors for self-signed certificates
    page.context.ignore_https_errors = True
    yield page
    context.close()


class TestOAuthFlow:
    """Test suite for OAuth 2.0 PKCE authentication flow."""

    def test_oauth_flow_complete(self, page):
        """Test complete OAuth flow: login page → Entra → callback → dashboard."""
        skip_if_no_credentials()

        # Step 1: Load login page
        page.goto(f"{STAGING_URL}/auth/login", wait_until="networkidle")

        # Verify login page loaded
        expect(page).to_have_title(
            (
                "Login - FMRIF Scheduler",
                "FMRIF Scheduler",
            )
        )

        # Step 2: Verify OAuth button exists
        oauth_button = page.locator('button:has-text("Login with NIH")')
        expect(oauth_button).to_be_visible()

        # Step 3: Click OAuth button (will redirect to Microsoft Entra)
        with page.expect_navigation():
            oauth_button.click()

        # Step 4: Wait for Entra login page to load
        page.wait_for_url(r".*login\.microsoftonline\.com.*")

        # Step 5: Enter credentials
        # Note: NIH Entra requires @nih.gov domain suffix
        username = OAUTH_TEST_USERNAME
        if not username.endswith("@nih.gov"):
            username = f"{username}@nih.gov"

        # Fill email field
        email_input = page.locator('input[name="loginfmt"]')
        expect(email_input).to_be_visible()
        email_input.fill(username)

        # Click Next
        next_button = page.locator('button:has-text("Next")')
        with page.expect_navigation():
            next_button.click()

        # Step 6: Enter password
        page.wait_for_url(r".*login\.microsoftonline\.com.*password.*", timeout=10000)

        password_input = page.locator('input[name="passwd"]')
        expect(password_input).to_be_visible()
        password_input.fill(OAUTH_TEST_PASSWORD)

        # Click Sign in
        signin_button = page.locator('button:has-text("Sign in")')
        with page.expect_navigation():
            signin_button.click()

        # Step 7: Handle potential MFA or additional prompts
        # This may redirect to /auth/callback or stay on Entra if MFA required
        try:
            page.wait_for_url(
                f"{STAGING_URL}/auth/callback*", timeout=15000, wait_until="networkidle"
            )
        except:
            # If callback takes longer, just wait for page to stabilize
            page.wait_for_load_state("networkidle", timeout=10000)

        # Step 8: Verify redirect back to application dashboard
        # After OAuth callback, should redirect to home page
        try:
            page.wait_for_url(f"{STAGING_URL}/$", timeout=10000)
            expect(page).to_have_url(f"{STAGING_URL}/")
        except:
            # If not redirected to home, verify we're back in the app (not on Entra)
            current_url = page.url
            assert (
                "login.microsoftonline.com" not in current_url
            ), f"Still on Entra login page: {current_url}"
            assert (
                STAGING_URL in current_url
            ), f"Not redirected to application: {current_url}"

        # Step 9: Verify authenticated (should see user info or dashboard content)
        # Example: Check for logout button or user menu
        user_menu = page.locator('button:has-text("Logout")')
        expect(user_menu).to_be_visible(timeout=5000)

        print("✅ OAuth flow test passed: Full authentication successful")

    def test_oauth_config_endpoint(self, page):
        """Test that OAuth configuration endpoint returns correct values."""
        skip_if_no_credentials()

        # Fetch OAuth config endpoint
        response = page.request.get(f"{STAGING_URL}/api/config/entra.json")
        assert response.status == 200, f"Config endpoint returned {response.status}"

        config = response.json()

        # Verify required fields exist
        required_fields = [
            "client_id",
            "tenant_id",
            "authorization_endpoint",
            "redirect_uri",
            "scope",
        ]
        for field in required_fields:
            assert field in config, f"Missing field in OAuth config: {field}"
            assert (
                config[field] and config[field] != "undefined"
            ), f"Field '{field}' has invalid value: {config[field]}"

        # Verify scope is not 'undefined'
        assert (
            config["scope"] != "undefined"
        ), "OAuth scope is 'undefined' - frontend will fail"
        assert (
            "openid" in config["scope"]
        ), "OAuth scope must include 'openid' for OIDC"

        print(f"✅ OAuth config test passed: Config is valid")
        print(f"   Scope: {config['scope']}")

    def test_login_page_loads(self, page):
        """Test that login page is accessible and renders correctly."""
        # This test runs even without credentials
        page.goto(f"{STAGING_URL}/auth/login", wait_until="networkidle")

        expect(page).to_have_title(
            (
                "Login - FMRIF Scheduler",
                "FMRIF Scheduler",
            )
        )

        # Verify OAuth button is present
        oauth_button = page.locator('button:has-text("Login with NIH")')
        expect(oauth_button).to_be_visible()

        print("✅ Login page test passed: Page loads and renders correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
