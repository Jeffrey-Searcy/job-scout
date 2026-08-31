"""
Job Scout MCP server.

Exposes the job-search app to AI agents (Claude Desktop, or your scheduled
scout) over the Model Context Protocol. Every tool is a thin wrapper over the
Django REST API — the MCP server holds no business logic of its own (API-first),
so the app stays the single source of truth.

Transport: stdio (the standard for local MCP clients). Point it at your running
backend via the JOBSCOUT_API_URL env var (default http://localhost:8000/api).

Add to Claude Desktop's config like:
    "job-scout": {
      "command": "python",
      "args": ["/absolute/path/to/mcp-server/server.py"],
      "env": {"JOBSCOUT_API_URL": "http://localhost:8000/api"}
    }
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

# Base URL of the running Django API. Overridable so the same server works
# against localhost, a docker host, or a remote deployment.
API = os.environ.get("JOBSCOUT_API_URL", "http://localhost:8000/api").rstrip("/")

# Per-task write credential, set by the host worker for a single scan/enrich run
# (agent_worker.py exports JOBSCOUT_TASK_TOKEN before launching Claude). When
# present, the write tools (add_lead / add_application) target the worker's
# token-scoped endpoints so every save is attributed to that task's owner. When
# absent (e.g. a human using this server from Claude Desktop against their own
# login session), the tools fall back to the session-authenticated endpoints.
#
# This is NOT a silent data fallback: the token only ever CHANGES WHICH URL and
# header are used. It never invents an owner or hides a failure — a missing token
# on the worker path simply means the server is being used interactively instead.
TASK_TOKEN = os.environ.get("JOBSCOUT_TASK_TOKEN", "").strip()

# Header name the worker API reads the task token from. Must match
# TASK_TOKEN_HEADER in backend/applications/worker_api.py.
TASK_TOKEN_HEADER = "X-Task-Token"

# The MCP server instance; the name is what shows up in the client's tool list.
mcp = FastMCP("job-scout")


def _client():
    """Return an httpx client with a sane timeout for local API calls.

    When a task token is set, every request carries it in the X-Task-Token
    header so the worker API can scope writes to the task's owner. Reads that go
    through the session-authenticated endpoints ignore the header harmlessly.
    """
    headers = {TASK_TOKEN_HEADER: TASK_TOKEN} if TASK_TOKEN else {}
    return httpx.Client(base_url=API, timeout=15.0, headers=headers)


@mcp.tool()
def pipeline_stats() -> dict:
    """Get pipeline metrics (totals, active count, funnel, new-lead count).

    Use this to answer "how's the job search going?" at a glance.
    """
    with _client() as c:
        return c.get("/stats/").json()


@mcp.tool()
def list_applications() -> list:
    """List every job application in the pipeline with its current status."""
    with _client() as c:
        return c.get("/applications/").json()


@mcp.tool()
def add_application(company: str, role: str, link: str = "", status: str = "applied",
                    work_mode: str = "unknown", location: str = "", is_local: bool = False,
                    fit: str = "good", notes: str = "") -> dict:
    """Add a new application directly to the pipeline.

    Use when the user has already applied somewhere. `status` is one of:
    applied, phone_screen, interview, take_home, onsite, offer, rejected, ghosted.
    """
    payload = dict(company=company, role=role, link=link, status=status,
                   work_mode=work_mode, location=location, is_local=is_local,
                   fit=fit, notes=notes)
    # On the worker path the task token scopes this write to the task's owner via
    # the token-authenticated endpoint; interactively it uses the session path.
    path = "/worker/applications/" if TASK_TOKEN else "/applications/"
    with _client() as c:
        return c.post(path, json=payload).json()


@mcp.tool()
def update_application_status(application_id: int, status: str) -> dict:
    """Advance an application to a new pipeline stage (e.g. 'phone_screen', 'offer')."""
    with _client() as c:
        return c.patch(f"/applications/{application_id}/", json={"status": status}).json()


@mcp.tool()
def list_leads(only_new: bool = True) -> list:
    """List scout leads. By default only 'new' (untriaged) leads are returned."""
    with _client() as c:
        leads = c.get("/leads/").json()
    return [l for l in leads if l.get("status") == "new"] if only_new else leads


@mcp.tool()
def add_lead(company: str, title: str, url: str = "", location: str = "",
             work_mode: str = "unknown", salary_text: str = "", source: str = "Scout",
             summary: str = "", is_local: bool = False, discovered_date: str = None) -> dict:
    """Add a discovered job posting to the scout inbox (does NOT apply).

    This is the tool the scheduled scout calls for each fresh match it finds.
    Duplicates (same company+title+url) are rejected by the API and reported here.
    `discovered_date` is an ISO date string (YYYY-MM-DD) or omitted.
    """
    payload = dict(company=company, title=title, url=url, location=location,
                   work_mode=work_mode, salary_text=salary_text, source=source,
                   summary=summary, is_local=is_local)
    if discovered_date:
        payload["discovered_date"] = discovered_date
    # On the worker path the task token scopes this write to the task's owner via
    # the token-authenticated endpoint; interactively it uses the session path.
    path = "/worker/leads/" if TASK_TOKEN else "/leads/"
    with _client() as c:
        resp = c.post(path, json=payload)
        if resp.status_code >= 400:
            # Most likely a duplicate; surface a friendly note instead of raising.
            return {"skipped": True, "reason": resp.text, "company": company, "title": title}
        return resp.json()


@mcp.tool()
def promote_lead(lead_id: int) -> dict:
    """Promote a scout lead into a real application (creates a pipeline entry)."""
    with _client() as c:
        return c.post(f"/leads/{lead_id}/promote/").json()


if __name__ == "__main__":
    # Run over stdio so MCP clients can launch this as a subprocess.
    mcp.run()
