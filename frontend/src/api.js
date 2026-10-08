// Access credentials and clinical data stay in memory. No production mock fallback.
let accessToken = null;
let epoch = 0;
let refreshPromise = null;
let expired = () => {};
export class ApiError extends Error {
  constructor(
    message,
    status = 0,
    code = "NETWORK_UNAVAILABLE",
    requestId = null,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}
export function onExpired(handler) {
  expired = handler;
}
export function clearSession() {
  accessToken = null;
  epoch += 1;
  refreshPromise = null;
}
export function setToken(token) {
  accessToken = token;
}
function csrf() {
  const cookie = document.cookie
    .split("; ")
    .find((value) => value.startsWith("csrf_token="));
  return cookie ? decodeURIComponent(cookie.slice(11)) : "";
}
async function responseError(response) {
  let value = {};
  try {
    value = await response.json();
  } catch {
    /* Only safe generic errors for non-JSON upstreams. */
  }
  return new ApiError(
    value.error?.message || "The request could not be completed.",
    response.status,
    value.error?.code || "REQUEST_FAILED",
    value.requestId || response.headers.get("X-Request-ID"),
  );
}
async function refresh() {
  if (!csrf())
    throw new ApiError("Please sign in to continue.", 401, "SESSION_EXPIRED");
  if (!refreshPromise) {
    const generation = epoch;
    refreshPromise = fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf() },
    })
      .then(async (response) => {
        if (!response.ok) throw await responseError(response);
        const value = await response.json();
        if (generation !== epoch)
          throw new ApiError("Session changed. Please sign in again.", 401);
        accessToken = value.data.accessToken;
      })
      .finally(() => {
        if (generation === epoch) refreshPromise = null;
      });
  }
  return refreshPromise;
}
export async function api(
  path,
  {
    method = "GET",
    body,
    key,
    anonymous = false,
    blob = false,
    retry = true,
  } = {},
) {
  const generation = epoch;
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!anonymous && accessToken)
    headers.Authorization = `Bearer ${accessToken}`;
  if (key) headers["Idempotency-Key"] = key;
  let response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "Connection unavailable. Check your connection and try again.",
    );
  }
  if (!anonymous && generation !== epoch)
    throw new ApiError("Session changed. Please sign in again.", 401);
  if (response.status === 401 && !anonymous && retry) {
    try {
      await refresh();
    } catch {
      if (generation === epoch) {
        clearSession();
        expired();
      }
      throw new ApiError(
        "Your session has expired. Please sign in again.",
        401,
        "SESSION_EXPIRED",
      );
    }
    return api(path, { method, body, key, anonymous, blob, retry: false });
  }
  if (response.status === 401 && !anonymous && generation === epoch) {
    clearSession();
    expired();
  }
  if (!response.ok) throw await responseError(response);
  if (blob) return response.blob();
  if (response.status === 204) return null;
  return (await response.json()).data;
}
export async function restoreSession() {
  if (!csrf()) return null;
  await refresh();
  return (await api("/auth/me")).user;
}
export async function signIn(email, password) {
  clearSession();
  const data = await api("/auth/login", {
    method: "POST",
    body: { email, password },
    anonymous: true,
  });
  setToken(data.accessToken);
  return data.user;
}
export async function signOut() {
  let error;
  try {
    const response = await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf() },
    });
    if (!response.ok) error = await responseError(response);
  } catch {
    error = new ApiError(
      "Sign-out could not reach the server. Local session cleared; retry server sign-out.",
    );
  } finally {
    clearSession();
  }
  if (error) throw error;
}
