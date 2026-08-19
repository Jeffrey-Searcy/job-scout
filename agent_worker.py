#!/usr/bin/env python3
"""
Host-side worker that turns dashboard button-presses into real AI work.

Why this exists: the app runs in Docker, but Claude Code (logged into your Max
plan) lives on the host. The dashboard buttons just create an "AgentTask" in the
database. This worker — run on the host, outside Docker — polls for pending
tasks and fulfills each one by invoking Claude Code headless with your project's
job-scout MCP server, so no API key is ever needed.

Run it from the project root (where Claude Code can see the local MCP config):
    python3 agent_worker.py

Leave it running in a terminal (or wrap it in a launchd/pm2 service later).

Config via environment:
    JOBSCOUT_API_URL   default http://localhost:8001/api
    CLAUDE_BIN         default "claude"
    CLAUDE_DANGEROUS   set to "1" if Claude Code keeps pausing for permission
                       (adds --dangerously-skip-permissions for this local worker)
"""
import json
import os
import subprocess
import time
import urllib.request

API = os.environ.get("JOBSCOUT_API_URL", "http://localhost:8001/api").rstrip("/")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
POLL_SECONDS = 4
# Verifying each posting is a direct, still-open link is slow, so give the
# headless Claude Code run a generous ceiling. Override with CLAUDE_TIMEOUT.
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
# How many leads a single scan aims for. Kept modest so link verification for
# every one fits inside CLAUDE_TIMEOUT. Override with SCAN_MAX_LEADS.
SCAN_MAX_LEADS = int(os.environ.get("SCAN_MAX_LEADS", "5"))

# Tools Claude Code is pre-authorized to use so it runs unattended.
ALLOWED_TOOLS = ",".join([
    "mcp__job-scout__add_lead",
    "mcp__job-scout__add_application",
    "mcp__job-scout__list_applications",
    "mcp__job-scout__list_leads",
    "mcp__job-scout__promote_lead",
    "mcp__job-scout__pipeline_stats",
    "WebSearch",
    "WebFetch",
])

# The candidate profile the scan targets. Loaded (in priority order) from the
# SCOUT_PROFILE env var, then a local scout_profile.txt beside this script, then a
# generic placeholder. Keep your real profile in scout_profile.txt (gitignored).
_DEFAULT_PROFILE = (
    "A software engineer seeking roles that match their stack and level. "
    "Set SCOUT_PROFILE or create scout_profile.txt to describe your experience, "
    "target titles/levels, core stack, and preferred locations/work modes."
)


def load_profile():
    """Return the candidate profile string from env, file, or a default."""
    env = os.environ.get("SCOUT_PROFILE")
    if env:
        return env.strip()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scout_profile.txt")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return _DEFAULT_PROFILE


PROFILE = load_profile()


def api_get(path):
    """GET helper returning parsed JSON."""
    with urllib.request.urlopen(f"{API}{path}", timeout=15) as r:
        return json.loads(r.read())


def api_patch(path, data):
    """PATCH helper (used to move a task through running -> done/error)."""
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def build_prompt(task):
    """Turn a task into a precise instruction for Claude Code."""
    if task["kind"] == "scan":
        return (
            "You have the job-scout MCP tools. FIRST, call mcp__job-scout__list_applications "
            "and mcp__job-scout__list_leads to see what is already in the pipeline and inbox. "
            "You must NOT re-suggest any role already there: skip a match if the same company "
            "appears with the same or a very similar role, or if the apply URL matches one that "
            "already exists. The candidate has already applied to those — surfacing them again is a bug.\n"
            "THEN search the web (LinkedIn, Indeed, Greenhouse, Lever, company sites) for NEW "
            "roles matching this profile:\n"
            f"{PROFILE}\n"
            f"Add each good, not-already-present match (up to {SCAN_MAX_LEADS}, prioritizing recent "
            "postings) by calling mcp__job-scout__add_lead with company, title, url, location, work_mode "
            "(onsite/hybrid/remote), salary_text, source, summary (one-line why-it-fits), "
            "and is_local=true for the candidate's local metro. Skip senior/staff (5+ yrs) unless a "
            "perfect match.\n"
            "LINK QUALITY: use the DIRECT apply URL on the company's own careers site or its ATS "
            "(Greenhouse/Lever/Workday/Ashby/SmartRecruiters/iCIMS), NOT aggregator links (Built In, "
            "ZipRecruiter, Indeed, Glassdoor). If found via an aggregator, follow through to the "
            "canonical company posting. VERIFY each role is still open; skip expired/removed ones.\n"
            "When done, reply with one line: how many leads you added."
        )
    if task["kind"] == "enrich":
        p = task.get("payload", {})
        return (
            "You have the job-scout MCP tools. Fetch this job posting: "
            f"{p.get('url')}\n"
            "For deciding is_local and fit, here is the candidate profile:\n"
            f"{PROFILE}\n"
            "Extract company, role/title, location, work_mode (onsite/hybrid/remote), and "
            "salary if listed. Then call mcp__job-scout__add_application with company, role, "
            f"link (the URL), status='{p.get('status', 'applied')}', work_mode, location, "
            "is_local (true if the role is in the candidate's local metro), fit ('good' unless "
            "clearly strong or a stretch), and a one-line notes summary. Reply with what you added."
        )
    return "Unknown task; do nothing and reply 'skipped'."


def run_claude(prompt):
    """Invoke Claude Code headless with the MCP + web tools; return its text output."""
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "text",
        "--allowedTools", ALLOWED_TOOLS,
        "--permission-mode", "acceptEdits",
    ]
    if os.environ.get("CLAUDE_DANGEROUS") == "1":
        cmd.append("--dangerously-skip-permissions")
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude exited non-zero")
    return proc.stdout.strip()


def handle(task):
    """Process one task end to end, updating its status/result as it goes."""
    tid = task["id"]
    api_patch(f"/agent-tasks/{tid}/", {"status": "running"})
    try:
        result = run_claude(build_prompt(task))
        api_patch(f"/agent-tasks/{tid}/", {"status": "done", "result": result[:4000]})
        print(f"[task {tid}] done: {result[:120]}")
    except Exception as e:  # noqa: BLE001 - report any failure back to the UI
        api_patch(f"/agent-tasks/{tid}/", {"status": "error", "result": str(e)[:4000]})
        print(f"[task {tid}] error: {e}")


def main():
    """Poll forever, handling pending tasks oldest-first."""
    print(f"Job Scout worker up. API={API}  project={PROJECT_ROOT}")
    print("Waiting for tasks (press the dashboard buttons to create them)...")
    while True:
        try:
            pending = api_get("/agent-tasks/?status=pending")
            for task in sorted(pending, key=lambda t: t["id"]):
                handle(task)
        except Exception as e:  # noqa: BLE001 - keep the loop alive on transient errors
            print("poll error:", e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
