# Entra Configuration (Deprecated)

This directory previously contained OAuth 2.0 / OIDC configuration for a browser-based SPA flow.
The application now uses a server-side OAuth flow; configuration is loaded from environment variables and
the frontend no longer reads `entra-config.json`.

## Files

- **`entra-config.json`** - Active configuration (loaded by frontend)
- **`entra-config.json.example`** - Template with placeholder values (reference only)
- **`README.md`** - This file

## Configuration Fields

### `client_id` (required)
The Application (client) ID registered in your Microsoft Entra app.

**Where to find:** Azure Portal → App registrations → Your app → Overview → Application (client) ID

**Format:** UUID (e.g., `00000000-0000-0000-0000-000000000000`)

### `tenant_id` (required)
The Directory (tenant) ID for your Microsoft Entra tenant.

**Where to find:** Azure Portal → App registrations → Your app → Overview → Directory (tenant) ID

**Format:** UUID (e.g., `14b77578-9773-42d5-8507-251ca2dc2b06`)

**Current value:** NIH tenant ID

### `redirect_uri` (required)
The exact URL where Entra will redirect after the user logs in. Must match exactly what's registered in your Entra app.

**Where to set in Entra:** Azure Portal → App registrations → Your app → Authentication → Redirect URIs

**Format:** Must be HTTPS (except for localhost development)

**Staging example:** `https://fmrif-schedule-backend-staging.nimh.nih.gov`

**Production example:** `https://fmrif-schedule-backend.nimh.nih.gov`

**Local development:** `http://localhost:8000` (if registered with Entra)

### `scope` (required)
OAuth scopes defining what permissions the app requests from the user.

**Current value:** `email openid profile offline_access`

**Meaning:**
- `email` - Access to user's email address
- `openid` - Standard OIDC scope (required)
- `profile` - Access to user's profile information
- `offline_access` - Permission to use refresh tokens

**Note:** For NIH, scopes are configured by the server and cannot be freely changed. Use whatever NIH Entra is configured to support.

### `discovery_url` (required)
The OpenID Connect Discovery endpoint. Returns metadata about all other endpoints.

**Format:** `https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration`

**Current value:** Uses NIH tenant ID

### `authorization_endpoint` (optional but recommended)
The endpoint where users are sent to authenticate. Normally fetched from discovery_url, but can be specified explicitly for performance.

**Format:** `https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize`

### `token_endpoint` (optional but recommended)
The endpoint where authorization codes are exchanged for tokens.

**Format:** `https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token`

### `userinfo_endpoint` (optional)
The endpoint that returns authenticated user information (email, name, etc).

**Format:** `https://graph.microsoft.com/oidc/userinfo`

---

## How to Update Configuration

### For Staging Deployment

1. Update `redirect_uri` to your staging domain
2. Ensure redirect URI is registered in Entra app
3. Verify `client_id` and `tenant_id` are correct
4. Commit `entra-config.json`
5. Deploy to staging

### For Production Deployment

1. Create new entry in Entra app registration with production domain
2. Update `redirect_uri` to production domain
3. Verify all other values are correct
4. Update `entra-config.json`
5. Commit and deploy

### For Local Development

Option 1: Register localhost with Entra
- Set `redirect_uri` to `http://localhost:8000`
- Register this URI in Entra app
- Update `entra-config.json`

Option 2: Use ngrok or similar (tunnel local to public URL)
- Start: `ngrok http 8000`
- Register the ngrok URL in Entra app
- Update `redirect_uri` in `entra-config.json`

---

## Security Notes

1. **Not Sensitive** - These values are public:
   - `client_id` - Can be public (no secret here)
   - `tenant_id` - Public knowledge
   - `redirect_uri` - Must be public (browser needs to know it)
   - Endpoints - Public discovery endpoint

2. **This file is committed to git** - It's safe to version control

3. **Backend secrets not included** - Backend handles its own secret for server-to-server calls if needed

---

## How Frontend Uses This

1. On page load, frontend fetches `entra-config.json`
2. When user clicks "Login", frontend uses these values to:
   - Generate PKCE verifier and challenge
   - Build authorization URL
   - Send authorization request to Entra
3. After user authenticates, frontend uses `token_endpoint` to exchange auth code for JWT
4. Frontend stores JWT and uses it for all API calls

---

## Troubleshooting

### "Failed to load config"
- Check file path: should be `/scheduler/static/config/entra-config.json`
- Check CORS if loading from different origin
- Check file syntax is valid JSON

### "redirect_uri mismatch"
- Verify redirect_uri value matches exactly what's registered in Entra
- Check for trailing slashes, protocols (http vs https), domains, ports
- Common mistakes: `localhost:8000` vs `localhost:8000/`, `http` vs `https`

### "Unauthorized client"
- Verify `client_id` is correct
- Verify `tenant_id` is correct
- Check that app is registered in the correct tenant

### "Invalid scope"
- Verify scopes are supported by your Entra tenant
- For NIH: use only scopes configured by NIH team

---

**Last Updated:** 2025-12-09
**Status:** Ready for Phase 1 implementation
