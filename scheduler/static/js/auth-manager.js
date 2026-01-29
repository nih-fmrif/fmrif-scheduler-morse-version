/**
 * OAuth 2.0 / OIDC Authentication Manager
 * Handles Microsoft Entra authentication flow with PKCE for browser-based SPA
 *
 * Uses PKCE (Proof Key for Code Exchange) for enhanced security:
 * - Browser-based tokens only (no backend token handling)
 * - Immune to authorization code interception attacks
 * - Complies with OAuth 2.0 and OIDC specifications
 */

// Configuration from entra-config.json
let entraConfig = null;

// Token storage (sessionStorage for browser-only, secure storage)
const TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const ID_TOKEN_KEY = "id_token";
const TOKEN_EXPIRY_KEY = "token_expiry";
const PKCE_VERIFIER_KEY = "pkce_verifier";

/**
 * Initialize authentication on page load
 *
 * On page load, this function:
 * 1. Loads Entra configuration from JSON
 * 2. Checks for existing token in sessionStorage
 * 3. If token exists and valid, enables the app
 * 4. If no token, shows login button
 * 5. Parses OAuth callback URL if present
 *
 * @returns {Promise<{isAuthenticated: boolean, token: string|null}>}
 *
 * @example
 * // Call on page load
 * const auth = await initializeAuth();
 * if (auth.isAuthenticated) {
 *   console.log('User already logged in');
 *   loadApplicationUI();
 * } else {
 *   console.log('User needs to login');
 *   showLoginButton();
 * }
 */
async function initializeAuth() {
  try {
    // Load Entra configuration
    const response = await fetch("/api/config/entra.json");
    if (!response.ok) {
      throw new Error(`Failed to load configuration: ${response.status}`);
    }
    entraConfig = await response.json();
    console.log("✓ Entra configuration loaded");

    // Check for token in sessionStorage
    const token = sessionStorage.getItem(TOKEN_KEY);
    const expiryTime = sessionStorage.getItem(TOKEN_EXPIRY_KEY);

    if (token && expiryTime) {
      // Check if token is still valid (not expired)
      const now = Date.now();
      if (parseInt(expiryTime) > now) {
        console.log("✓ Valid token found in sessionStorage");
        return { isAuthenticated: true, token };
      } else {
        // Token expired, try to refresh
        console.log("Token expired, attempting refresh...");
        const storedRefreshToken = sessionStorage.getItem(REFRESH_TOKEN_KEY);
        if (storedRefreshToken) {
          const newAuth = await refreshToken();
          if (newAuth && newAuth.token) {
            return { isAuthenticated: true, token: newAuth.token };
          }
        }
        // Refresh failed, clear tokens
        clearTokens();
        return { isAuthenticated: false, token: null };
      }
    }

    // Check for OAuth callback
    if (window.location.search.includes("code=")) {
      console.log("OAuth callback detected, handling...");
      await handleOAuthCallback();
      const newToken = sessionStorage.getItem(TOKEN_KEY);
      if (newToken) {
        return { isAuthenticated: true, token: newToken };
      }
    }

    // No token and no callback
    console.log("No authentication found");
    return { isAuthenticated: false, token: null };
  } catch (error) {
    console.error("Authentication initialization failed:", error);
    return { isAuthenticated: false, token: null };
  }
}

/**
 * Start OAuth 2.0 authorization flow
 *
 * This function:
 * 1. Generates a PKCE verifier
 * 2. Computes the code challenge
 * 3. Stores verifier in sessionStorage (for later token exchange)
 * 4. Builds the authorization URL with all required parameters
 * 5. Redirects to Entra login page
 *
 * User will see Microsoft Entra login with:
 * - PIV card authentication (smart card)
 * - Multi-factor authentication (MFA)
 * - Interactive login flow
 *
 * After successful authentication, Entra redirects back to redirect_uri
 * with authorization code in query parameter
 *
 * @returns {Promise<void>}
 * @throws {Error} If configuration is not loaded
 *
 * @example
 * // Call when user clicks "Login" button
 * const loginBtn = document.getElementById('login-btn');
 * loginBtn.addEventListener('click', async () => {
 *   loginBtn.disabled = true;
 *   loginBtn.textContent = 'Redirecting to NIH...';
 *   await startOAuthFlow();
 * });
 */
async function startOAuthFlow() {
  if (!entraConfig) {
    throw new Error("Configuration not loaded. Call initializeAuth() first.");
  }

  try {
    // Step 1: Generate PKCE verifier
    const verifier = generateVerifier();
    sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
    console.log("✓ PKCE verifier generated and stored");

    // Step 2: Generate code challenge from verifier
    const challenge = await pkceChallenge(verifier);
    console.log("✓ PKCE challenge generated");

    // Step 3: Build authorization URL parameters
    // Using URLSearchParams for proper encoding
    const params = new URLSearchParams({
      client_id: entraConfig.client_id,
      response_type: "code",
      response_mode: "query",
      redirect_uri: entraConfig.redirect_uri,
      scope: entraConfig.scope,
      code_challenge: challenge,
      code_challenge_method: "S256",
      // Optional: Add state parameter for CSRF protection
      state: generateRandomState(),
    });

    // Step 4: Build full authorization URL
    const authUrl = `${
      entraConfig.authorization_endpoint
    }?${params.toString()}`;
    console.log("✓ Authorization URL built");

    // Step 5: Redirect to Entra (in same window, will redirect back to redirect_uri)
    window.location.href = authUrl;
  } catch (error) {
    console.error("Failed to start OAuth flow:", error);
    throw error;
  }
}

/**
 * Handle OAuth callback from Entra redirect
 *
 * Called when Entra redirects back to redirect_uri with authorization code.
 * This typically happens automatically when entra-config.json's redirect_uri
 * points to the same application.
 *
 * This function:
 * 1. Extracts authorization code from URL query parameter
 * 2. Retrieves PKCE verifier from sessionStorage
 * 3. Calls exchangeCodeForToken to get JWT tokens
 * 4. Stores tokens in sessionStorage
 * 5. Cleans up URL (removes code parameter)
 *
 * @returns {Promise<{access_token: string|null}>}
 *
 * @example
 * // Called automatically during initialization
 * const auth = await initializeAuth();
 * // If URL has code parameter, handleOAuthCallback is called
 */
async function handleOAuthCallback() {
  try {
    // Step 1: Extract code from URL
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (!code) {
      console.warn("No authorization code in callback");
      return { access_token: null };
    }

    console.log("✓ Authorization code extracted from callback");

    // Step 2: Get PKCE verifier from sessionStorage
    const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY);
    if (!verifier) {
      throw new Error(
        "PKCE verifier not found. Authorization may have expired.",
      );
    }

    // Step 3: Exchange code for tokens
    const tokens = await exchangeCodeForToken(code, verifier);
    if (!tokens || !tokens.access_token) {
      throw new Error("Token exchange failed");
    }

    // Step 4: Store tokens in sessionStorage
    sessionStorage.setItem(TOKEN_KEY, tokens.access_token);
    if (tokens.refresh_token) {
      sessionStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    }
    if (tokens.id_token) {
      sessionStorage.setItem(ID_TOKEN_KEY, tokens.id_token);
    }

    // Store token expiry time (typically 1 hour from now)
    const expiresIn = tokens.expires_in || 3600; // Default 1 hour
    const expiryTime = Date.now() + expiresIn * 1000;
    sessionStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());

    console.log("✓ Tokens stored in sessionStorage");

    // Step 5: Clean up URL (remove code parameter)
    window.history.replaceState({}, document.title, window.location.pathname);
    console.log("✓ URL cleaned up");

    return { access_token: tokens.access_token };
  } catch (error) {
    console.error("OAuth callback handling failed:", error);
    clearTokens();
    throw error;
  }
}

/**
 * Exchange authorization code for JWT tokens
 *
 * Makes a POST request to Entra's token endpoint with:
 * - Authorization code (from callback)
 * - PKCE verifier (for PKCE validation)
 * - Client ID
 * - Redirect URI (must match what was registered in Entra)
 *
 * Entra responds with:
 * - access_token: JWT for API calls
 * - id_token: JWT containing user claims
 * - refresh_token: Can be used to get new access_token
 * - expires_in: Seconds until access_token expires (usually 3600)
 *
 * @param {string} code - Authorization code from OAuth callback
 * @param {string} verifier - PKCE verifier (from sessionStorage)
 * @returns {Promise<{access_token: string, refresh_token: string|null, id_token: string|null, expires_in: number}>}
 * @throws {Error} If token exchange fails
 *
 * @example
 * const code = 'M.R3_BAA...'; // From OAuth callback
 * const verifier = sessionStorage.getItem('pkce_verifier');
 * const tokens = await exchangeCodeForToken(code, verifier);
 * console.log(tokens.access_token); // JWT token
 */
async function exchangeCodeForToken(code, verifier) {
  if (!entraConfig) {
    throw new Error("Configuration not loaded");
  }

  try {
    // Build request body with URLSearchParams (required by Entra)
    const params = new URLSearchParams({
      grant_type: "authorization_code",
      client_id: entraConfig.client_id,
      code: code,
      redirect_uri: entraConfig.redirect_uri,
      code_verifier: verifier,
      // Note: For public client (no client_secret), these are not needed
      // For confidential client with secret, add:
      // client_secret: entraConfig.client_secret,
    });

    // Make POST request to token endpoint
    const response = await fetch(entraConfig.token_endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: params.toString(),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Token endpoint error:", errorText);
      throw new Error(`Token exchange failed: ${response.status} ${errorText}`);
    }

    const tokens = await response.json();
    console.log("✓ Tokens received from Entra");

    return {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token || null,
      id_token: tokens.id_token || null,
      expires_in: tokens.expires_in || 3600,
    };
  } catch (error) {
    console.error("Token exchange error:", error);
    throw error;
  }
}

/**
 * Refresh access token using refresh token
 *
 * When access_token expires, this function uses the refresh_token
 * to get a new access_token without requiring user to login again.
 *
 * The refresh_token grant allows offline_access (user not required to be present).
 *
 * @returns {Promise<{token: string}|null>} New tokens or null if refresh fails
 *
 * @example
 * // Check if token is about to expire
 * const expiryTime = parseInt(sessionStorage.getItem('token_expiry'));
 * const now = Date.now();
 * const timeToExpire = (expiryTime - now) / 1000 / 60; // Minutes
 *
 * if (timeToExpire < 5) { // Less than 5 minutes
 *   await refreshToken();
 * }
 */
async function refreshToken() {
  if (!entraConfig) {
    console.error("Configuration not loaded");
    return null;
  }

  try {
    const refreshToken = sessionStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) {
      console.warn("No refresh token available");
      return null;
    }

    // Build request body for refresh token grant
    const params = new URLSearchParams({
      grant_type: "refresh_token",
      client_id: entraConfig.client_id,
      refresh_token: refreshToken,
      scope: entraConfig.scope,
    });

    // Make POST request to token endpoint
    const response = await fetch(entraConfig.token_endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: params.toString(),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Token refresh failed:", response.status, errorText);
      // If refresh fails, clear tokens (user needs to login again)
      clearTokens();
      return null;
    }

    const tokens = await response.json();
    console.log("✓ Tokens refreshed");

    // Store new tokens
    sessionStorage.setItem(TOKEN_KEY, tokens.access_token);
    if (tokens.refresh_token) {
      sessionStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    }

    // Update expiry time
    const expiresIn = tokens.expires_in || 3600;
    const expiryTime = Date.now() + expiresIn * 1000;
    sessionStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());

    return { token: tokens.access_token };
  } catch (error) {
    console.error("Token refresh error:", error);
    clearTokens();
    return null;
  }
}

/**
 * Get current access token from sessionStorage
 *
 * Used by API client and other modules to get the current JWT token.
 *
 * @returns {string|null} Current access token or null if not authenticated
 *
 * @example
 * const token = getAccessToken();
 * if (!token) {
 *   console.log('User not authenticated');
 *   await startOAuthFlow();
 * }
 */
function getAccessToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

/**
 * Check if user is currently authenticated
 *
 * Checks both token existence and expiry time.
 *
 * @returns {boolean} True if valid token exists, false otherwise
 *
 * @example
 * if (!isAuthenticated()) {
 *   showLoginButton();
 * }
 */
function isAuthenticated() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const expiryTime = sessionStorage.getItem(TOKEN_EXPIRY_KEY);

  if (!token || !expiryTime) {
    return false;
  }

  // Check if token is still valid (not expired)
  const now = Date.now();
  return parseInt(expiryTime) > now;
}

/**
 * Logout and clear all tokens
 *
 * Clears tokens from sessionStorage and optionally
 * redirects to Entra logout endpoint to clear Entra session.
 *
 * @param {boolean} [redirectToEntra=false] If true, also logout from Entra
 * @returns {Promise<void>}
 *
 * @example
 * // Logout and clear tokens only
 * await logout();
 *
 * // Logout and also clear Entra session
 * await logout(true);
 */
async function logout(redirectToEntra = false) {
  clearTokens();
  console.log("✓ Tokens cleared");

  if (redirectToEntra && entraConfig) {
    // Redirect to Entra logout endpoint
    // This logs out the user from all Entra applications
    const logoutUrl = `${entraConfig.authorization_endpoint.replace(
      "/authorize",
      "/logout",
    )}?client_id=${entraConfig.client_id}`;
    window.location.href = logoutUrl;
  }
}

/**
 * Clear all authentication tokens from sessionStorage
 *
 * @private
 */
function clearTokens() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  sessionStorage.removeItem(ID_TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_EXPIRY_KEY);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
}

/**
 * Generate random state parameter for CSRF protection
 *
 * The state parameter should be validated on callback to prevent
 * Cross-Site Request Forgery (CSRF) attacks.
 *
 * @returns {string} Random state string
 * @private
 */
function generateRandomState() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

// Export functions for use in other modules
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    initializeAuth,
    startOAuthFlow,
    handleOAuthCallback,
    exchangeCodeForToken,
    refreshToken,
    getAccessToken,
    isAuthenticated,
    logout,
  };
}
