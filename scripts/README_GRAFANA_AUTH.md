# Grafana SSO Token Extractor

Automates browser-based authentication through ELB → Cognito → Entra SAML and extracts JWT tokens for API usage.

## Features

- **Manual or Automated Login**: Supports both automated login with credentials and manual browser-based authentication
- **Multiple Browser Engines**: Choose between webkit, chromium, or firefox
- **Token Extraction**: Automatically extracts JWT tokens from multiple sources (localStorage, sessionStorage, network requests, cookies)
- **MFA Support**: Manual mode allows you to complete multi-factor authentication in the browser
- **Headless or Visible**: Run headless for automation or with visible browser for debugging
- **Secure Token Storage**: Tokens saved with restrictive file permissions (0600)

## Security Best Practices

⚠️ **Important Security Considerations:**

- **Manual Login Recommended**: Use manual login mode for interactive use to avoid exposing credentials
- **No Password Arguments**: The `--password` command-line argument has been removed for security. Passwords should only be provided via environment variables for automation scenarios
- **HTTPS Only**: The script enforces HTTPS to prevent credential/token interception
- **Token Protection**: Generated token files are created with 0600 permissions (owner read/write only)
- **Debug Mode**: Token previews are only shown when using `--debug` flag to prevent accidental exposure
- **Keep Tokens Secret**: Never commit token files to version control - add `grafana_token.txt` to `.gitignore`
- **Token Expiration**: JWT tokens typically expire after a few hours - re-authenticate when you get 401 errors

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
playwright install webkit  # or chromium/firefox
```

## Usage

### Manual Login Mode (Recommended for MFA)

```bash
# Opens browser window for you to complete authentication manually
python grafana_auth.py --url REDACTED/

# Specify browser engine (default: webkit)
python grafana_auth.py --url REDACTED/ --browser chromium
```

### Automated Login Mode

⚠️ **Security Note**: Only use automated mode for CI/CD pipelines or trusted automation environments.

```bash
# Use environment variables for credentials (SECURE)
export GRAFANA_USERNAME=your.email@example.com
export GRAFANA_PASSWORD=yourpassword
python grafana_auth.py --url https://your-grafana-url/

# Run headless (no browser window) for automation
export GRAFANA_USERNAME=your.email@example.com
export GRAFANA_PASSWORD=yourpassword
python grafana_auth.py \
  --url https://your-grafana-url/ \
  --headless
```

### Command Line Options

- `--url`: Grafana URL (required, must be HTTPS)
- `--username`: Username for automated login (optional, can also use GRAFANA_USERNAME env var)
- `--output`: Output file for token (default: grafana_token.txt)
- `--headless`: Run in headless mode (only works with automated login)
- `--manual`: Force manual login mode even if credentials are provided
- `--browser`: Browser engine to use: webkit (default), chromium, or firefox
- `--debug`: Enable debug output including token preview (use with caution)

This will save the JWT token to `grafana_token.txt` (or your specified output file)

### Use Token with curl

```bash
# Direct curl usage
curl -H "Authorization: Bearer $(cat grafana_token.txt)" \
  REDACTED/api/dashboards/home

# Using the helper script
chmod +x grafana_curl.sh
./grafana_curl.sh REDACTED/api/dashboards/home

# Make multiple requests
./grafana_curl.sh REDACTED/api/search
./grafana_curl.sh REDACTED/api/datasources
```

## Token Refresh

JWT tokens typically expire after a few hours. When you get 401 errors, re-run the auth script:

```bash
python grafana_auth.py --url REDACTED/
```

## .gitignore

Add the following to your `.gitignore` to prevent accidentally committing tokens:

```
grafana_token.txt
*.token
```

## Troubleshooting

### Token not found
If the script can't automatically find the token in automated mode, the script will pause and display debugging information including:
- List of cookies found
- localStorage keys available

You can also run in manual mode without headless to see the browser and inspect it:
```bash
python grafana_auth.py --url REDACTED/
```

Then inspect with browser DevTools (F12):
1. Check the Network tab for Authorization headers
2. Check Application → Storage → Local Storage for tokens
3. Check Application → Cookies for auth cookies

### MFA/2FA
If you have MFA enabled, use manual login mode (default when no credentials provided) to complete the MFA prompt manually in the browser window:
```bash
python grafana_auth.py --url REDACTED/
```

### Custom token location
The script looks for tokens in:
- localStorage (keys containing 'token' or 'auth')
- sessionStorage
- Authorization headers in network requests
- Cookies containing 'token' or 'auth'

If your Grafana stores tokens elsewhere, you may need to modify `grafana_auth.py`.

## Example API Calls

```bash
# List all dashboards
./grafana_curl.sh REDACTED/api/search

# Get dashboard by UID
./grafana_curl.sh REDACTED/api/dashboards/uid/DASHBOARD_UID

# Query datasource
./grafana_curl.sh -X POST \
  REDACTED/api/datasources/proxy/1/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "up"}'

# Get org preferences
./grafana_curl.sh REDACTED/api/org/preferences
```
