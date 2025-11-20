#!/usr/bin/env python3
"""
Grafana SSO Token Extractor
Automates browser-based authentication through ELB → Cognito → Entra SAML
and extracts JWT token for API usage.
"""

import os
import sys
import json
import argparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout  # type: ignore


class GrafanaAuthenticator:
    def __init__(
        self,
        grafana_url,
        username=None,
        password=None,
        headless=True,
        manual_login=False,
        browser_type='webkit',
        debug=False
    ):
        self.grafana_url = grafana_url
        self.username = username
        self.password = password
        self.headless = headless
        self.manual_login = manual_login
        self.browser_type = browser_type
        self.debug = debug
        self.token = None

    def extract_token_from_storage(self, page):
        """Extract JWT token from browser storage"""
        try:
            # Try localStorage
            token = page.evaluate("() => localStorage.getItem('grafana_token') || localStorage.getItem('auth_token')")
            if token:
                return token

            # Try sessionStorage
            token = page.evaluate("() => sessionStorage.getItem('grafana_token') || sessionStorage.getItem('auth_token')")
            if token:
                return token

            # Try to find token in all localStorage keys
            all_storage = page.evaluate("() => Object.entries(localStorage)")
            for key, value in all_storage:
                if 'token' in key.lower() or 'auth' in key.lower():
                    try:
                        # Try to parse as JSON in case it's wrapped
                        parsed = json.loads(value)
                        if isinstance(parsed, dict) and 'token' in parsed:
                            return parsed['token']
                        return value
                    except (json.JSONDecodeError, TypeError, ValueError):
                        return value

            return None
        except (RuntimeError, ValueError) as e:
            print(f"Error extracting token from storage: {e}")
            return None


    def authenticate(self):
        """Run the authentication flow"""
        with sync_playwright() as p:
            # Select browser type
            if self.browser_type == 'webkit':
                browser_engine = p.webkit
            elif self.browser_type == 'firefox':
                browser_engine = p.firefox
            else:
                browser_engine = p.chromium

            # Launch browser
            browser = browser_engine.launch(headless=self.headless)
            context = browser.new_context(
                viewport={'width': 1280, 'height': 720}
            )
            page = context.new_page()

            # Store Authorization headers from requests
            auth_token = None

            def handle_request(request):
                nonlocal auth_token
                auth_header = request.headers.get('authorization', '')
                if auth_header.startswith('Bearer '):
                    auth_token = auth_header.replace('Bearer ', '')

            def handle_response(response):
                nonlocal auth_token
                # Check for token in response headers or body
                if 'application/json' in response.headers.get('content-type', ''):
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            if 'token' in body:
                                auth_token = body['token']
                            elif 'access_token' in body:
                                auth_token = body['access_token']
                    except (json.JSONDecodeError, ValueError, KeyError):
                        pass

            page.on('request', handle_request)
            page.on('response', handle_response)

            try:
                print(f"Navigating to Grafana: {self.grafana_url}")
                page.goto(self.grafana_url, wait_until='networkidle', timeout=60000)

                # Wait for redirect to Cognito/Entra
                print("Waiting for SSO redirect...")
                page.wait_for_timeout(2000)

                # Handle Entra (Azure AD) login
                print(f"Current URL: {page.url}")

                # Manual login mode - wait for user to complete authentication
                if self.manual_login or not self.username or not self.password:
                    print("\n" + "="*60)
                    print("MANUAL LOGIN MODE")
                    print("="*60)
                    print("Please complete the authentication in the browser window.")
                    print("The script will automatically detect when you've logged in.")
                    print("="*60 + "\n")

                    # Wait for user to complete login and return to Grafana
                    print("Waiting for you to complete authentication...")
                    page.wait_for_url(f"{self.grafana_url}*", timeout=300000)  # 5 minute timeout
                    print(f"✓ Authentication detected! Current URL: {page.url}")

                else:
                    # Automated login mode
                    # Look for Microsoft/Entra login form
                    if 'microsoftonline' in page.url or 'login.microsoft' in page.url:
                        print("Detected Microsoft Entra login page")

                        # Enter username
                        print("Entering username...")
                        page.fill('input[type="email"], input[name="loginfmt"], input[name="username"]', self.username)
                        page.click('input[type="submit"], button[type="submit"]')
                        page.wait_for_timeout(2000)

                        # Enter password
                        print("Entering password...")
                        page.fill('input[type="password"], input[name="passwd"], input[name="password"]', self.password)
                        page.click('input[type="submit"], button[type="submit"]')
                        page.wait_for_timeout(2000)

                        # Handle "Stay signed in?" prompt
                        try:
                            page.wait_for_selector('input[type="submit"]', timeout=5000)
                            print("Handling 'Stay signed in' prompt...")
                            page.click('input[type="submit"]')
                        except PlaywrightTimeout:
                            pass  # No "Stay signed in" prompt, continue

                    # Handle generic Cognito login
                    elif 'amazoncognito' in page.url or 'cognito' in page.url:
                        print("Detected Cognito login page")
                        page.fill('input[name="username"]', self.username)
                        page.fill('input[name="password"]', self.password)
                        page.click('button[type="submit"], input[type="submit"]')

                    # Wait for redirect back to Grafana
                    print("Waiting for redirect back to Grafana...")
                    page.wait_for_url(f"{self.grafana_url}*", timeout=30000)
                    print(f"Successfully authenticated! Current URL: {page.url}")

                # Give the app time to store tokens
                page.wait_for_timeout(3000)

                # Extract token from various sources
                print("\nExtracting JWT token...")

                # Try localStorage/sessionStorage first
                self.token = self.extract_token_from_storage(page)

                # Try from intercepted requests
                if not self.token and auth_token:
                    self.token = auth_token

                # Try to extract from cookies
                if not self.token:
                    cookies = context.cookies()
                    for cookie in cookies:
                        if 'token' in cookie['name'].lower() or 'auth' in cookie['name'].lower():
                            self.token = cookie['value']
                            break

                if self.token:
                    print("✓ Token extracted successfully!")
                    if self.debug:
                        print(f"Token preview: {self.token[:50]}..." if len(self.token) > 50 else self.token)
                else:
                    print("✗ Could not extract token automatically")
                    print("\nDebugging information:")
                    print(f"Cookies: {[c['name'] for c in context.cookies()]}")
                    print(f"localStorage keys: {page.evaluate('() => Object.keys(localStorage)')}")
                    print("\nPlease inspect the browser to find where the token is stored.")
                    print("Press Enter when ready to close browser...")
                    input()

            except PlaywrightTimeout as e:
                print(f"Timeout error: {e}")
                print("The authentication flow took too long. Please check the URL and credentials.")
            except Exception as e:
                print(f"Error during authentication: {e}")
                import traceback
                traceback.print_exc()
            finally:
                browser.close()

        return self.token

    def save_token(self, filepath):
        """Save token to file with secure permissions (0600)"""
        if not self.token:
            print("No token to save")
            return False

        try:
            # Set umask to create file with restrictive permissions
            old_umask = os.umask(0o077)
            try:
                with open(filepath, 'w') as f:
                    f.write(self.token)
            finally:
                os.umask(old_umask)

            # Verify and set permissions explicitly (in case file already existed)
            os.chmod(filepath, 0o600)
            print(f"Token saved to: {filepath} (permissions: 0600)")
            return True
        except Exception as e:
            print(f"Error saving token: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description='Extract Grafana JWT token via SSO authentication')
    parser.add_argument('--url', required=True, help='Grafana URL (must be HTTPS)')
    parser.add_argument('--username', help='Username (optional - will open browser for manual login if not provided)')
    parser.add_argument('--output', default='grafana_token.txt', help='Output file for token')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (no browser window)')
    parser.add_argument('--manual', action='store_true', help='Force manual login mode')
    parser.add_argument('--browser', default='webkit', choices=['webkit', 'chromium', 'firefox'],
                        help='Browser engine to use (default: webkit, works best on macOS)')
    parser.add_argument('--debug', action='store_true', help='Enable debug output including token preview')

    args = parser.parse_args()

    # Validate URL
    if not args.url.startswith('https://'):
        print("Error: URL must use HTTPS for security")
        sys.exit(1)

    # Get credentials from args or environment
    # NOTE: Password from command line is insecure - use environment variable or manual mode
    username = args.username or os.getenv('GRAFANA_USERNAME')
    password = os.getenv('GRAFANA_PASSWORD')

    # Determine if manual login is needed
    manual_login = args.manual or not username or not password

    if manual_login:
        print("Starting in MANUAL LOGIN mode - browser window will open")
        print("Complete the authentication in the browser window\n")
    else:
        print("Starting in AUTOMATED mode with provided credentials\n")

    # Authenticate and extract token
    auth = GrafanaAuthenticator(
        grafana_url=args.url,
        username=username,
        password=password,
        headless=args.headless and not manual_login,  # Never headless for manual login
        manual_login=manual_login,
        browser_type=args.browser,
        debug=args.debug
    )

    token = auth.authenticate()

    if token:
        auth.save_token(args.output)
        print("\n✓ Success! You can now use the token with curl:")
        print(f'curl -H "Authorization: Bearer $(cat {args.output})" {args.url}/api/...')
    else:
        print("\n✗ Failed to extract token")
        sys.exit(1)


if __name__ == '__main__':
    main()
