"""
Shared Twelve Data API client with automatic key fallback.

Every module that needs a Twelve Data price or time series should call
twelvedata_get() instead of hitting requests.get() directly. It tries
TWELVE_DATA_API_KEY first, and if that key comes back rate-limited,
invalid, or erroring, it automatically retries the same request with
TWELVE_DATA_API_KEY_2 (when configured) before giving up.
"""

import requests
import config


def _is_error_response(res):
    """Detects Twelve Data's error payload shape, e.g. rate limits (429)
    or bad keys (401/403), so we know to try the next key."""
    if not isinstance(res, dict):
        return False
    if res.get("status") == "error":
        return True
    code = res.get("code")
    if isinstance(code, int) and code >= 400:
        return True
    return False


def twelvedata_get(endpoint, params, timeout=10):
    """
    Calls https://api.twelvedata.com/{endpoint} with the given params,
    trying each configured API key in turn until one succeeds.

    endpoint: e.g. "price" or "time_series"
    params:   dict of query params WITHOUT apikey (it's added per attempt)

    Returns the parsed JSON response (dict). On total failure, returns
    the last error payload received so callers can still log/inspect it.
    """
    last_result = {"status": "error", "message": "No Twelve Data API key configured."}

    if not config.TWELVE_DATA_KEYS:
        print("Twelve Data error: no API keys configured (TWELVE_DATA_API_KEY / _2).")
        return last_result

    for key in config.TWELVE_DATA_KEYS:
        query = dict(params)
        query["apikey"] = key
        try:
            res = requests.get(f"https://api.twelvedata.com/{endpoint}", params=query, timeout=timeout).json()
        except Exception as e:
            print(f"Twelve Data request error (key ...{key[-4:]}, endpoint {endpoint}): {e}")
            last_result = {"status": "error", "message": str(e)}
            continue

        if _is_error_response(res):
            print(f"Twelve Data key ...{key[-4:]} failed on {endpoint}: {res.get('message', res)}. Trying next key.")
            last_result = res
            continue

        return res

    return last_result
