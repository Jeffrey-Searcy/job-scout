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
# How many leads a single scan aims for. Kept small so following each posting to
# its canonical link and confirming it's still open fits inside CLAUDE_TIMEOUT.
# Scans that aimed for 5 kept getting killed at the ceiling; 3 finishes cleanly.
# Override with SCAN_MAX_LEADS.
SCAN_MAX_LEADS = int(os.environ.get("SCAN_MAX_LEADS", "3"))

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
# SCOUT_PROFILE env var, then a cached scout_profile.txt, then — if you dropped a
# resume.pdf beside this script — a profile distilled from that resume (written
# back to scout_profile.txt so it is only distilled once), then a generic
# placeholder. Keep your real profile/resume out of git (both are gitignored).
_DEFAULT_PROFILE = (
    "A software engineer seeking roles that match their stack and level. "
    "Set SCOUT_PROFILE or create scout_profile.txt to describe your experience, "
    "target titles/levels, core stack, and preferred locations/work modes."
)

# Where the cached text profile and the optional drop-in resume live. Both sit
# beside this script and are gitignored, so a candidate's real data never ships.
PROFILE_PATH = os.path.join(PROJECT_ROOT, "scout_profile.txt")
RESUME_PATH = os.path.join(PROJECT_ROOT, "resume.pdf")


def distill_resume_to_profile(resume_path, out_path):
    """Read a resume PDF with Claude Code and write a tight search profile.

    Why Claude instead of a Python PDF parser: the worker is intentionally
    stdlib-only (nothing to pip-install), and Claude Code can already read a PDF
    directly. We distill ONCE and cache the result to out_path, so later scans
    reuse the short profile and never re-read the whole PDF (which would be slow).

    Returns the distilled profile string. Raises on failure — we never silently
    fall back to a wrong/empty profile, since that would send the scan hunting
    for the wrong candidate. The caller decides what to do with the error.
    """
    prompt = (
        "Read the resume PDF at this path: " + resume_path + "\n"
        "Write a concise job-search profile (5-8 sentences, plain prose, no "
        "preamble) that a scout can use to find matching roles. Cover: years of "
        "experience and level (junior/mid/senior), target job titles, core "
        "technical stack, notable domains, and preferred locations plus work mode "
        "(onsite/hybrid/remote). Output ONLY the profile text — no headings, no "
        "'Here is', no bullet list."
    )
    # This call only reads a local file; no MCP tools or web access needed.
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "text",
        "--allowedTools", "Read",
        "--permission-mode", "acceptEdits",
    ]
    if os.environ.get("CLAUDE_DANGEROUS") == "1":
        cmd.append("--dangerously-skip-permissions")
    proc = subprocess.run(
        cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude exited non-zero while reading resume")
    profile = proc.stdout.strip()
    if not profile:
        raise RuntimeError("resume distillation produced an empty profile")
    with open(out_path, "w") as f:
        f.write(profile + "\n")
    print(f"Distilled resume.pdf -> scout_profile.txt ({len(profile)} chars)")
    return profile


def load_profile():
    """Return the candidate profile string from env, cache, resume, or default.

    Precedence:
      1. SCOUT_PROFILE env var (explicit override).
      2. scout_profile.txt (the cache; also where a distilled resume lands).
      3. resume.pdf, distilled once into scout_profile.txt.
      4. A generic placeholder.
    """
    env = os.environ.get("SCOUT_PROFILE")
    if env:
        return env.strip()
    if os.path.exists(PROFILE_PATH):
        with open(PROFILE_PATH) as f:
            return f.read().strip()
    if os.path.exists(RESUME_PATH):
        # No cached profile yet, but a resume is present: distill it once. Let a
        # failure surface loudly rather than silently scanning for no one.
        return distill_resume_to_profile(RESUME_PATH, PROFILE_PATH)
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
            "You have the job-scout MCP tools. Search the web (LinkedIn, Indeed, "
            "Greenhouse, Lever, company sites) for NEW roles matching this profile:\n"
            f"{PROFILE}\n"
            f"Find up to {SCAN_MAX_LEADS} good matches, prioritizing recent postings. "
            "IMPORTANT — work one lead at a time and SAVE AS YOU GO: as soon as you have "
            "verified a single role, immediately call mcp__job-scout__add_lead for it before "
            "you start looking for the next one. Do not batch them up to save at the end — if "
            "this run is cut short, every lead you already saved must already be in the inbox.\n"
            "Call mcp__job-scout__add_lead with company, title, url, location, work_mode "
            "(onsite/hybrid/remote), salary_text, source, summary (one-line why-it-fits), "
            "and is_local=true for the candidate's local metro. Skip senior/staff (5+ yrs) unless a "
            "perfect match.\n"
            "Do NOT spend time cross-checking your finds against the existing pipeline: the API "
            "automatically rejects any posting already applied to or already in the inbox (you will "
            "get an error on add_lead for those, which is expected — just move on to the next).\n"
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


class ClaudeTimeout(Exception):
    """Raised when the headless Claude Code run exceeds CLAUDE_TIMEOUT.

    Kept distinct from a normal RuntimeError so the caller can treat a timeout as
    a possible PARTIAL success (a scan may have already saved some leads before it
    was killed) rather than a flat failure.
    """


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
    try:
        proc = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        # Surface as our own type so handle() can check for leads saved before the kill.
        raise ClaudeTimeout(f"claude run exceeded {CLAUDE_TIMEOUT}s")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude exited non-zero")
    return proc.stdout.strip()


def lead_count():
    """Return how many leads currently exist, or None if the API can't be read.

    Used to detect a scan's partial progress after a timeout. Returns None (not 0)
    on any read failure, so a failed count is never mistaken for 'no leads added'.
    """
    try:
        data = api_get("/leads/")
        rows = data if isinstance(data, list) else data.get("results", [])
        return len(rows)
    except Exception:  # noqa: BLE001 - a count we can't read is 'unknown', not zero
        return None


def handle(task):
    """Process one task end to end, updating its status/result as it goes.

    Scans save leads incrementally, so a run that times out may still have added
    real leads. We snapshot the lead count before a scan starts; if the run then
    times out, we compare counts and report those leads as a partial success (a
    'done' with a note) rather than a scary 'error' that hides them.
    """
    tid = task["id"]
    # Snapshot lead count before a scan so a later timeout can be judged partial.
    leads_before = lead_count() if task["kind"] == "scan" else None
    api_patch(f"/agent-tasks/{tid}/", {"status": "running"})
    try:
        result = run_claude(build_prompt(task))
        api_patch(f"/agent-tasks/{tid}/", {"status": "done", "result": result[:4000]})
        print(f"[task {tid}] done: {result[:120]}")
    except ClaudeTimeout as e:
        # Did the scan save anything before it was killed? If so, that's a partial
        # win, not a failure. Only usable when we have both before/after counts.
        added = None
        if leads_before is not None:
            leads_after = lead_count()
            if leads_after is not None:
                added = leads_after - leads_before
        if added and added > 0:
            note = (f"Added {added} lead(s), then the run hit the {CLAUDE_TIMEOUT}s "
                    "limit before finishing. Your new leads are in the inbox.")
            api_patch(f"/agent-tasks/{tid}/", {"status": "done", "result": note})
            print(f"[task {tid}] partial: {note}")
        else:
            # Timed out with nothing to show for it — that IS a failure, report it.
            msg = f"Timed out after {CLAUDE_TIMEOUT}s with no leads added."
            api_patch(f"/agent-tasks/{tid}/", {"status": "error", "result": msg})
            print(f"[task {tid}] error: {msg}")
    except Exception as e:  # noqa: BLE001 - report any other failure back to the UI
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
