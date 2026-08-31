// Thin API client: every network call the UI makes lives here (single source of
// truth for endpoints). The app talks to the relative "/api" base, which Vite
// (dev) or nginx (Docker) proxies to Django.
//
// AUTH MODEL: the backend uses Django session cookies. Two things make that work
// from this SPA:
//   1. credentials: "include" on every request, so the browser sends (and
//      stores) the session cookie even though the API is a separate origin.
//   2. A CSRF token on every unsafe request (POST/PATCH/PUT/DELETE). Django sets
//      a `csrftoken` cookie (via the /auth/me/ endpoint, which is decorated with
//      ensure_csrf_cookie); we read it and echo it back in the X-CSRFToken
//      header, which is how Django's CsrfViewMiddleware verifies the caller.
const BASE = "/api";

// Read a cookie value by name (used for the CSRF token). Returns "" if absent,
// never guesses — a missing token surfaces as a real 403 from the server rather
// than being masked here.
function getCookie(name) {
  const prefix = name + "=";
  const parts = document.cookie ? document.cookie.split("; ") : [];
  for (const part of parts) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return "";
}

// Methods that change state and therefore need a CSRF token.
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// Core fetch wrapper: JSON in/out, sends the session cookie + CSRF token, throws
// on non-2xx so callers can catch. The thrown Error carries `.status` so callers
// (e.g. the auth gate) can tell 401/403 apart from other failures.
async function http(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (UNSAFE.has(method)) headers["X-CSRFToken"] = getCookie("csrftoken");
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: "include", // send/receive the Django session + csrf cookies
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = new Error(`${method} ${path} -> ${res.status}`);
    err.status = res.status;
    // Attach the parsed error body when present so callers can show the server's
    // own message (e.g. "username already taken") instead of a generic string.
    try {
      err.data = await res.json();
    } catch {
      err.data = null;
    }
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

// Send a multipart form (used for the resume PDF upload). Kept separate from
// http() because the body is FormData, not JSON, and the browser must set the
// multipart Content-Type/boundary itself — so we do NOT set Content-Type here.
async function httpForm(path, { method = "PUT", form }) {
  const headers = {};
  if (UNSAFE.has(method)) headers["X-CSRFToken"] = getCookie("csrftoken");
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    const err = new Error(`${method} ${path} -> ${res.status}`);
    err.status = res.status;
    try {
      err.data = await res.json();
    } catch {
      err.data = null;
    }
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

// Prime the CSRF cookie. Call once on app load before any unsafe request so the
// csrftoken cookie exists (the endpoint is decorated with ensure_csrf_cookie).
export const primeCsrf = () => http("/auth/csrf/");

// Who am I? Returns the user object when logged in; throws with .status 403/401
// when not. The auth gate uses this to decide login screen vs dashboard.
export const getMe = () => http("/auth/me/");

// Create an account and log in (open sign-up on the private Tailscale network).
export const signup = (username, password) =>
  http("/auth/signup/", { method: "POST", body: { username, password } });

// Log in with an existing account.
export const login = (username, password) =>
  http("/auth/login/", { method: "POST", body: { username, password } });

// Log out (clears the session on the server).
export const logout = () => http("/auth/logout/", { method: "POST" });

// ---------------------------------------------------------------------------
// Resume
// ---------------------------------------------------------------------------

// Get the current user's resume status (profile_ready etc.), or null if none
// uploaded yet (the endpoint returns 404, which we translate to null here so the
// UI can simply show the empty state).
export const getResume = async () => {
  try {
    return await http("/resume/");
  } catch (e) {
    if (e.status === 404) return null;
    throw e;
  }
};

// Upload or replace the resume PDF. `file` is a File from an <input type=file>.
export const uploadResume = (file) => {
  const form = new FormData();
  form.append("pdf", file);
  return httpForm("/resume/", { method: "PUT", form });
};

// Remove the current user's resume entirely.
export const deleteResume = () => http("/resume/", { method: "DELETE" });

// ---------------------------------------------------------------------------
// Pipeline data (all scoped server-side to the logged-in user)
// ---------------------------------------------------------------------------

// Pipeline metrics for the tiles + funnel.
export const getStats = () => http("/stats/");

// All applications in the pipeline.
export const getApplications = () => http("/applications/");

// Create a brand-new application from the add form.
export const createApplication = (data) => http("/applications/", { method: "POST", body: data });

// Patch any subset of fields on an application (edit form + status dropdown).
export const updateApplication = (id, data) => http(`/applications/${id}/`, { method: "PATCH", body: data });

// Convenience wrapper for the inline status dropdown.
export const updateApplicationStatus = (id, status) => updateApplication(id, { status });

// Remove an application entirely.
export const deleteApplication = (id) => http(`/applications/${id}/`, { method: "DELETE" });

// Attach (or replace) the resume you submitted for THIS application. `file` is a
// File from an <input type=file> — a PDF or .docx. Sent as multipart, so we use
// httpForm (not http, which is JSON). Returns the updated application, whose
// resume_file block then carries the download link. The backend rejects (400) a
// wrong file type or an oversized file — the caller shows that server message.
export const attachApplicationResume = (id, file) => {
  const form = new FormData();
  form.append("resume", file);
  return httpForm(`/applications/${id}/resume/`, { method: "POST", form });
};

// Remove the resume attached to this application.
export const deleteApplicationResume = (id) =>
  http(`/applications/${id}/resume/`, { method: "DELETE" });

// The login-gated download URL for an application's attached resume. Like the
// tailored-resume URL, we do NOT fetch it through http() — it is a file the
// browser saves, so callers point an anchor at this URL. The session cookie goes
// automatically because it is same-origin.
export const applicationResumeUrl = (id) => `${BASE}/applications/${id}/resume/download/`;

// Scout leads, optionally filtered by status (e.g. "new").
export const getLeads = (status) =>
  http(status ? `/leads/?status=${status}` : "/leads/");

// Mark a lead dismissed so it drops out of the inbox.
export const dismissLead = (id) =>
  http(`/leads/${id}/`, { method: "PATCH", body: { status: "dismissed" } });

// Start tailoring the user's resume to ONE lead's real posting. Returns the
// created AgentTask (kind "tailor") so the caller can poll it like a scan; when
// it finishes, the lead carries a downloadable tailored resume. The backend
// rejects this (400) if the lead has no URL or the user has no resume yet — the
// caller shows that server message.
export const tailorLead = (id) =>
  http(`/leads/${id}/tailor/`, { method: "POST" });

// The login-gated download URL for a lead's tailored resume (.docx). We do NOT
// fetch it through http() (which parses JSON) — this is a file the browser saves,
// so callers point a link/anchor at this URL and let the browser download it. The
// cookie goes automatically because it is same-origin.
export const tailoredResumeUrl = (id) => `${BASE}/leads/${id}/tailored-resume/`;

// Create an AI work request (kind: "scan" | "enrich"). The host worker fulfills it.
export const createAgentTask = (kind, payload = {}) =>
  http("/agent-tasks/", { method: "POST", body: { kind, payload } });

// Fetch one agent task to poll its status/result.
export const getAgentTask = (id) => http(`/agent-tasks/${id}/`);
