/**
 * API Client using server-side session cookies
 * Wraps fetch() for JSON requests and error handling
 *
 * Features:
 * - Sends same-origin cookies by default
 * - Handles 401 Unauthorized responses
 * - JSON serialization/deserialization
 * - Structured error responses
 * - Logging for debugging
 */

/**
 * Make API call using session cookies
 *
 * This is the main wrapper function for all API requests.
 * Automatically handles:
 * - JSON serialization/deserialization
 * - Error handling
 *
 * @param {string} method - HTTP method (GET, POST, PUT, DELETE, PATCH)
 * @param {string} url - API endpoint URL
 * @param {object} [data=null] - Request body data (for POST, PUT, PATCH)
 * @param {object} [options={}] - Additional options
 * @param {object} [options.headers={}] - Additional headers to merge
 * @param {boolean} [options.json=true] - Parse response as JSON
 * @returns {Promise<{ok: boolean, status: number, data: any, error: string|null}>}
 *
 * @throws {Error} If network error
 *
 * @example
 * // GET request
 * const response = await apiCall('GET', '/api/schedule');
 * if (response.ok) {
 *   console.log('Schedule:', response.data);
 * } else {
 *   console.error('Error:', response.error);
 * }
 *
 * @example
 * // POST request with data
 * const response = await apiCall('POST', '/api/events', {
 *   title: 'Team Meeting',
 *   startTime: '2025-12-15T10:00:00Z'
 * });
 * if (!response.ok) {
 *   alert('Failed to create event: ' + response.error);
 * }
 *
 * @example
 * // With custom headers
 * const response = await apiCall('POST', '/api/data', data, {
 *   headers: { 'X-Custom-Header': 'value' }
 * });
 */
async function apiCall(method, url, data = null, options = {}) {
  const { headers = {}, json = true } = options;

  try {
    // Step 1: Build request headers
    const requestHeaders = {
      "Content-Type": "application/json",
      ...headers,
    };

    // Step 2: Build fetch options
    const fetchOptions = {
      method: method,
      headers: requestHeaders,
      credentials: "same-origin",
    };

    // Step 3: Add body for requests that need it
    if (data && (method === "POST" || method === "PUT" || method === "PATCH")) {
      fetchOptions.body = JSON.stringify(data);
    }

    // Step 4: Make the API call
    console.log(`${method} ${url}`);
    const response = await fetch(url, fetchOptions);

    // Step 5: Handle response
    const responseData = json ? await response.json() : await response.text();

    if (response.ok) {
      console.log(`✓ ${method} ${url} (${response.status})`);
      return {
        ok: true,
        status: response.status,
        data: responseData,
        error: null,
      };
    }

    // Step 6: Handle error responses
    if (response.status === 401) {
      console.warn("Received 401 Unauthorized");
      return {
        ok: false,
        status: response.status,
        data: responseData,
        error: "Unauthorized",
      };
    }

    // Other error status codes
    const errorMessage =
      responseData?.error || responseData?.message || `HTTP ${response.status}`;

    console.error(`✗ ${method} ${url} (${response.status}): ${errorMessage}`);

    return {
      ok: false,
      status: response.status,
      data: responseData,
      error: errorMessage,
    };
  } catch (error) {
    console.error(`API call failed: ${error.message}`);
    return {
      ok: false,
      status: 0,
      data: null,
      error: error.message,
    };
  }
}

/**
 * GET request helper
 *
 * Shortcut for GET requests without body data.
 *
 * @param {string} url - API endpoint URL
 * @param {object} [options={}] - Additional options (see apiCall)
 * @returns {Promise<{ok, status, data, error}>}
 *
 * @example
 * const response = await apiGet('/api/schedule');
 * if (response.ok) {
 *   console.log('Schedule:', response.data);
 * }
 */
async function apiGet(url, options = {}) {
  return apiCall("GET", url, null, options);
}

/**
 * POST request helper
 *
 * Shortcut for POST requests with body data.
 *
 * @param {string} url - API endpoint URL
 * @param {object} data - Request body data
 * @param {object} [options={}] - Additional options (see apiCall)
 * @returns {Promise<{ok, status, data, error}>}
 *
 * @example
 * const response = await apiPost('/api/events', {
 *   title: 'Team Meeting',
 *   startTime: '2025-12-15T10:00:00Z'
 * });
 */
async function apiPost(url, data, options = {}) {
  return apiCall("POST", url, data, options);
}

/**
 * PUT request helper
 *
 * Shortcut for PUT requests (full resource update).
 *
 * @param {string} url - API endpoint URL
 * @param {object} data - Request body data
 * @param {object} [options={}] - Additional options (see apiCall)
 * @returns {Promise<{ok, status, data, error}>}
 *
 * @example
 * const response = await apiPut('/api/events/123', {
 *   title: 'Updated Meeting',
 *   startTime: '2025-12-15T14:00:00Z'
 * });
 */
async function apiPut(url, data, options = {}) {
  return apiCall("PUT", url, data, options);
}

/**
 * PATCH request helper
 *
 * Shortcut for PATCH requests (partial resource update).
 *
 * @param {string} url - API endpoint URL
 * @param {object} data - Request body data (only fields to update)
 * @param {object} [options={}] - Additional options (see apiCall)
 * @returns {Promise<{ok, status, data, error}>}
 *
 * @example
 * const response = await apiPatch('/api/events/123', {
 *   title: 'Rescheduled Meeting'
 * });
 */
async function apiPatch(url, data, options = {}) {
  return apiCall("PATCH", url, data, options);
}

/**
 * DELETE request helper
 *
 * Shortcut for DELETE requests.
 *
 * @param {string} url - API endpoint URL
 * @param {object} [options={}] - Additional options (see apiCall)
 * @returns {Promise<{ok, status, data, error}>}
 *
 * @example
 * const response = await apiDelete('/api/events/123');
 * if (response.ok) {
 *   console.log('Event deleted');
 * }
 */
async function apiDelete(url, options = {}) {
  return apiCall("DELETE", url, null, options);
}

/**
 * Parse API error response
 *
 * Extract meaningful error message from API response.
 * Handles various error response formats:
 * - `{error: "message"}`
 * - `{message: "message"}`
 * - `{detail: "message"}`
 * - String message
 * - HTTP status text
 *
 * @param {any} responseData - Response body data
 * @param {number} status - HTTP status code
 * @returns {string} Error message
 *
 * @example
 * const response = await apiCall('GET', '/api/data');
 * if (!response.ok) {
 *   const errorMsg = parseErrorResponse(response.data, response.status);
 *   console.error(errorMsg);
 * }
 *
 * @private
 */
function parseErrorResponse(responseData, status) {
  if (typeof responseData === "string") {
    return responseData;
  }

  if (typeof responseData === "object" && responseData !== null) {
    return (
      responseData.error ||
      responseData.message ||
      responseData.detail ||
      JSON.stringify(responseData)
    );
  }

  // Fallback to HTTP status text
  const statusTexts = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
  };

  return statusTexts[status] || `HTTP ${status}`;
}

/**
 * Execute multiple API calls in parallel
 *
 * Useful for loading related data that can be fetched simultaneously.
 *
 * @param {Array<[string, string, object]>} calls - Array of [method, url, data] tuples
 * @returns {Promise<Array<{ok, status, data, error}>>}
 *
 * @example
 * // Load schedule, events, and resources in parallel
 * const results = await apiCallParallel([
 *   ['GET', '/api/schedule'],
 *   ['GET', '/api/events'],
 *   ['GET', '/api/resources']
 * ]);
 *
 * const [scheduleResp, eventsResp, resourcesResp] = results;
 * if (scheduleResp.ok && eventsResp.ok && resourcesResp.ok) {
 *   loadDashboard(scheduleResp.data, eventsResp.data, resourcesResp.data);
 * } else {
 *   console.error('Failed to load data:', results);
 * }
 */
async function apiCallParallel(calls) {
  const promises = calls.map(([method, url, data = null]) =>
    apiCall(method, url, data),
  );
  return Promise.all(promises);
}

/**
 * Handle common API error patterns
 *
 * Maps API error responses to appropriate user-facing messages.
 * Can be customized for your specific API.
 *
 * @param {number} status - HTTP status code
 * @param {string} errorMessage - Error message from API
 * @returns {string} User-friendly error message
 *
 * @example
 * const response = await apiCall('POST', '/api/events', data);
 * if (!response.ok) {
 *   const friendlyMsg = handleApiError(response.status, response.error);
 *   showErrorNotification(friendlyMsg);
 * }
 *
 * @private
 */
function handleApiError(status, errorMessage) {
  const errorMap = {
    400: "Invalid request data. Please check your input.",
    401: "Your session has expired. Please login again.",
    403: "You do not have permission to perform this action.",
    404: "The requested resource was not found.",
    409: "This resource conflicts with existing data.",
    429: "Too many requests. Please try again later.",
    500: "Server error. Please try again later.",
    502: "Service temporarily unavailable. Please try again later.",
    503: "Service is under maintenance. Please try again later.",
  };

  if (status in errorMap) {
    return errorMap[status];
  }

  if (errorMessage && errorMessage.length > 0) {
    return errorMessage;
  }

  return "An unexpected error occurred. Please try again.";
}

/* global module */
// Export functions for use in other modules
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    apiCall,
    apiGet,
    apiPost,
    apiPut,
    apiPatch,
    apiDelete,
    apiCallParallel,
    parseErrorResponse,
    handleApiError,
  };
}
