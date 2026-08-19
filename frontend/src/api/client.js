// Thin API client: every network call the UI makes lives here (single source of
// truth for endpoints). The app talks to the relative "/api" base, which Vite
// (dev) or nginx (Docker) proxies to Django.
const BASE = "/api";

// Core fetch wrapper: JSON in/out, throws on non-2xx so callers can catch.
async function http(path, { method = "GET", body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}

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

// Scout leads, optionally filtered by status (e.g. "new").
export const getLeads = (status) =>
  http(status ? `/leads/?status=${status}` : "/leads/");

// Mark a lead dismissed so it drops out of the inbox.
export const dismissLead = (id) =>
  http(`/leads/${id}/`, { method: "PATCH", body: { status: "dismissed" } });

// Create an AI work request (kind: "scan" | "enrich"). The host worker fulfills it.
export const createAgentTask = (kind, payload = {}) =>
  http("/agent-tasks/", { method: "POST", body: { kind, payload } });

// Fetch one agent task to poll its status/result.
export const getAgentTask = (id) => http(`/agent-tasks/${id}/`);
