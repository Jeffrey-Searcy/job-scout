#!/usr/bin/env python3
"""
Host-side worker that turns dashboard button-presses into real AI work.

Why this exists: the app runs in Docker, but Claude Code (logged into your Max
plan) lives on the host. The dashboard buttons just create an "AgentTask" in the
database. This worker — run on the host, outside Docker — polls for pending
tasks and fulfills each one by invoking Claude Code headless with your project's
job-scout MCP server, so no API key is ever needed.

MULTI-USER: one worker serves EVERY user from one shared queue. It has no login.
It authenticates in two clearly separated ways:

  1. A shared worker secret (WORKER_SHARED_SECRET) lets it READ the cross-user
     pending queue and POST distilled resume profiles back. Read/queue access
     only — it never picks whose account a save lands in.

  2. A per-task token (handed to it in the queue payload) scopes every WRITE for
     that task to that task's OWNER. The worker exports it as JOBSCOUT_TASK_TOKEN
     so the MCP add_lead / add_application tools attribute each save correctly.

Each task in the queue already carries its owner's distilled resume profile, so
the worker searches for the RIGHT person every time — there is no single global
profile any more. If a task's owner has a resume PDF but no profile yet, the
worker distills the PDF once and posts the profile back so later scans reuse it.

Run it from the project root (where Claude Code can see the local MCP config):
    python3 agent_worker.py

Leave it running in a terminal (or wrap it in a launchd/pm2 service later).

Config via environment:
    JOBSCOUT_API_URL        default http://127.0.0.1:8001/api
                            NOTE: we default to 127.0.0.1, NOT "localhost". On
                            macOS, Python resolves "localhost" to IPv6 ::1 first,
                            but Docker's published port forward on ::1 mangles the
                            request (bad Host header -> Django 400/500). Pinning
                            IPv4 avoids that dual-stack trap. Override this var
                            only if the backend is genuinely on another host.
    WORKER_SHARED_SECRET    REQUIRED — same value as the server's env. The worker
                            refuses to start without it (it could not read the
                            queue anyway).
    CLAUDE_BIN              default "claude"
    CLAUDE_DANGEROUS        set to "1" if Claude Code keeps pausing for permission
                            (adds --dangerously-skip-permissions for this local worker)
"""
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

# Default to 127.0.0.1 (IPv4), NOT "localhost". See the module docstring: on
# macOS "localhost" resolves to IPv6 ::1 first, and Docker's ::1 port forward
# breaks the request. Pinning IPv4 is the root fix, not a workaround.
API = os.environ.get("JOBSCOUT_API_URL", "http://127.0.0.1:8001/api").rstrip("/")
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

# The shared secret that lets THIS worker read the cross-user queue and post
# distilled profiles back. Must equal the server's WORKER_SHARED_SECRET. No
# default: a worker with no secret cannot read the queue, so we refuse to start
# rather than spin uselessly (fail loud, not silent).
WORKER_SHARED_SECRET = os.environ.get("WORKER_SHARED_SECRET", "").strip()

# Header names — must match backend/applications/worker_api.py exactly.
WORKER_SECRET_HEADER = "X-Worker-Secret"
# The per-task write token header. The MCP tools send this on add_lead /
# add_application; the tailor path sends it directly when it posts the finished
# resume back. Must match TASK_TOKEN_HEADER in worker_api.py.
TASK_TOKEN_HEADER = "X-Task-Token"

# Tools Claude Code is pre-authorized to use so it runs unattended. On the worker
# path we authorize ONLY the two write tools plus web access. The read/list/stats
# tools are deliberately withheld: a scan does not need them, and withholding
# them means the worker's Claude run can never list another user's data. Every
# write it does make is scoped to the task's owner by the task token.
ALLOWED_TOOLS = ",".join([
    "mcp__job-scout__add_lead",
    "mcp__job-scout__add_application",
    "WebSearch",
    "WebFetch",
])


def _request(path, method="GET", data=None, extra_headers=None):
    """Low-level HTTP helper returning parsed JSON (or None for empty bodies).

    Adds the shared worker secret header on every call so the worker API accepts
    the request. ``extra_headers`` lets a caller add e.g. Content-Type. Raises
    urllib.error.HTTPError on a 4xx/5xx so the caller sees real failures instead
    of a silent wrong result.
    """
    headers = {WORKER_SECRET_HEADER: WORKER_SHARED_SECRET}
    if extra_headers:
        headers.update(extra_headers)
    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API}{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def get_queue():
    """Fetch the cross-user pending queue (list of task dicts) from the worker API."""
    return _request("/worker/tasks/", method="GET")


def set_task_status(tid, status, result=None):
    """PATCH a task's status/result via the worker API (retires its token on done/error)."""
    payload = {"status": status}
    if result is not None:
        payload["result"] = result[:4000]
    return _request(f"/worker/tasks/{tid}/", method="PATCH", data=payload)


def save_profile(tid, profile):
    """POST a freshly distilled resume profile back to the task owner's Resume."""
    return _request(f"/worker/tasks/{tid}/profile/", method="PUT", data={"profile": profile})


def save_tailored_resume(task_token, lead_id, job_url, keywords, resume):
    """POST finished tailored-resume content back; the backend builds the .docx.

    Scoped by the per-task token (X-Task-Token), exactly like add_lead — the
    backend attributes the write to the token's owner and refuses to attach the
    resume to anyone else's lead. ``resume`` is the structured dict Claude
    produced (name/contact/summary/skills/experience/education/extra). The backend
    turns it into an ATS-safe Word document and stores it on the lead.

    Raises urllib.error.HTTPError on a non-2xx so a bad payload or a rejected
    token surfaces as a real failure the task reports, not a silent miss.
    """
    return _request(
        "/worker/tailored-resume/",
        method="POST",
        data={
            "lead_id": lead_id,
            "job_url": job_url,
            "keywords": keywords,
            "resume": resume,
        },
        extra_headers={TASK_TOKEN_HEADER: task_token},
    )


def download_resume_pdf(tid, dest_path):
    """Download the task owner's resume PDF (over HTTP) to ``dest_path``.

    Why over HTTP, not off disk: the worker runs on the host, outside Docker. The
    resume PDFs live on a Docker volume that only exists INSIDE the backend
    container, so there is no filesystem path the host can read. The backend
    exposes the bytes at /worker/tasks/<id>/resume.pdf, gated by the shared
    worker secret and scoped to the task's owner. We stream them to a temp file
    the caller then hands to Claude for distillation, and deletes afterward.

    Raises urllib.error.HTTPError on a non-2xx (e.g. 404 when the owner has no
    PDF) so the caller surfaces the real problem instead of a silent empty file.
    """
    req = urllib.request.Request(
        f"{API}/worker/tasks/{tid}/resume.pdf",
        headers={WORKER_SECRET_HEADER: WORKER_SHARED_SECRET},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as r, open(dest_path, "wb") as f:
        # Stream in chunks so a large-ish PDF never sits fully in memory.
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)


def distill_resume_to_profile(resume_path):
    """Read a resume PDF with Claude Code and return a tight search profile string.

    Why Claude instead of a Python PDF parser: the worker is intentionally
    stdlib-only (nothing to pip-install), and Claude Code can already read a PDF
    directly. We distill once per owner and cache the result server-side (via
    save_profile), so later scans reuse the short profile and never re-read the
    whole PDF (which would be slow).

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
    return profile


def ensure_profile(task):
    """Return the search profile for this task's owner, distilling the PDF if needed.

    Precedence, per owner (never a shared/global profile):
      1. The profile already distilled and stored on the owner's Resume (arrives
         in the queue payload as ``profile``).
      2. If that is empty but the owner uploaded a PDF (``has_resume_pdf``),
         download the PDF over HTTP to a temp file, distill it once, save the
         profile back for reuse, and use it.
      3. Otherwise there is nothing to search for — raise, so the task fails
         loudly with a clear message. We do NOT invent a generic profile; a scan
         with no resume would just hunt for the wrong person.

    The PDF is fetched from the backend (not read off disk) because the worker
    runs on the host, where the Docker media volume does not exist. We write it
    to a NamedTemporaryFile, hand that path to Claude, and always delete it.
    """
    profile = (task.get("profile") or "").strip()
    if profile:
        return profile
    if not task.get("has_resume_pdf"):
        raise RuntimeError(
            "This account has no resume yet. Upload a resume PDF in the app, "
            "then run the scan again."
        )
    tid = task["id"]
    # Download the owner's PDF to a temp file, distill it, then clean up. The
    # try/finally only removes the temp file — it does NOT swallow errors; a
    # download or distillation failure propagates so the task fails loudly.
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix=f"resume_task{tid}_")
    os.close(fd)  # we only wanted the unique path; download_resume_pdf reopens it
    try:
        download_resume_pdf(tid, tmp_path)
        profile = distill_resume_to_profile(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass  # temp file already gone; nothing to clean up
    # Cache it server-side so the next scan for this owner skips distillation.
    save_profile(tid, profile)
    return profile


def build_prompt(task, profile):
    """Turn a task into a precise instruction for Claude Code, using OWNER's profile."""
    if task["kind"] == "scan":
        return (
            "You have the job-scout MCP tools. Search the web (LinkedIn, Indeed, "
            "Greenhouse, Lever, company sites) for NEW roles matching this profile:\n"
            f"{profile}\n"
            f"Find up to {SCAN_MAX_LEADS} good matches, prioritizing recent postings. "
            "IMPORTANT — work one lead at a time and SAVE AS YOU GO: as soon as you have "
            "verified a single role, immediately call mcp__job-scout__add_lead for it before "
            "you start looking for the next one. Do not batch them up to save at the end — if "
            "this run is cut short, every lead you already saved must already be in the inbox.\n"
            "Call mcp__job-scout__add_lead with company, title, url, location, work_mode "
            "(onsite/hybrid/remote), salary_text, source, summary (one-line why-it-fits), "
            "and is_local=true for the candidate's local metro. Skip senior/staff (5+ yrs) unless a "
            "perfect match.\n"
            # Per-company cap: without this one heavily-hiring company (e.g. Twilio) can fill the
            # whole inbox in a single scan. The user chose a max of 2 roles per company per run.
            "PER-COMPANY LIMIT: add AT MOST 2 roles from any single company in this run. If a company "
            "has more than 2 good matches, pick the 2 strongest for this profile and skip the rest.\n"
            # The API only rejects an EXACT duplicate (same company+title+url). It does NOT reject a
            # different role at a company already in the inbox/pipeline — so the scanner must check
            # itself. Telling it "the API handles all dedup" was false and let repeats through.
            "AVOID REPEATS: before saving, call mcp__job-scout__list_leads(only_new=False) once to see "
            "what is ALREADY in the inbox (any status, including applied/dismissed). Do NOT re-add a "
            "posting whose URL already appears there. The API also rejects an exact company+title+url "
            "duplicate outright (add_lead returns a 'skipped' note) — that is expected; just move on.\n"
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
            f"{profile}\n"
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


def run_claude(prompt, task_token):
    """Invoke Claude Code headless with the MCP + web tools; return its text output.

    ``task_token`` is exported to the subprocess as JOBSCOUT_TASK_TOKEN so the MCP
    server scopes every add_lead / add_application write to this task's owner. The
    worker process itself never holds a login — only this per-run token.
    """
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "text",
        "--allowedTools", ALLOWED_TOOLS,
        "--permission-mode", "acceptEdits",
    ]
    if os.environ.get("CLAUDE_DANGEROUS") == "1":
        cmd.append("--dangerously-skip-permissions")
    # Child env = our env plus the per-task write token. The MCP server (launched
    # by Claude as a child) reads JOBSCOUT_TASK_TOKEN and sends it as X-Task-Token.
    child_env = dict(os.environ)
    child_env["JOBSCOUT_TASK_TOKEN"] = task_token
    try:
        proc = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT, env=child_env,
        )
    except subprocess.TimeoutExpired:
        # Surface as our own type so handle() can check for leads saved before the kill.
        raise ClaudeTimeout(f"claude run exceeded {CLAUDE_TIMEOUT}s")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude exited non-zero")
    return proc.stdout.strip()


def build_tailor_prompt(resume_path, job_url):
    """Instruction for Claude to tailor a resume to one posting, output as JSON.

    The hard rules here are the honesty guardrails the whole feature rests on:
    rephrase and surface only what the resume already supports, match the job's
    real keywords, and NEVER invent a skill, tool, employer, date, or number. The
    output is a single JSON object the worker parses and posts back; the backend
    turns it into the .docx.
    """
    return (
        "You tailor a resume to ONE job posting so it passes ATS keyword screens, "
        "WITHOUT lying.\n\n"
        "STEP 1: Read the candidate's resume PDF at this path:\n"
        f"  {resume_path}\n"
        "STEP 2: Fetch the full job posting and read it carefully:\n"
        f"  {job_url}\n\n"
        "STEP 3: Rewrite the resume to match the posting's real language.\n"
        "HARD RULES (do not break these):\n"
        "  - Use ONLY facts, skills, tools, employers, titles, dates and numbers "
        "that already appear in the candidate's resume. NEVER invent or add a "
        "skill the resume does not support. NEVER change dates, employers, or job "
        "titles.\n"
        "  - You MAY rephrase existing content to use the posting's exact wording "
        "(e.g. resume says 'REST APIs', posting says 'RESTful services' -> use "
        "'RESTful services'; resume says 'Postgres', posting says 'PostgreSQL' -> "
        "spell it 'PostgreSQL'). Surfacing a real skill in the job's words is the "
        "goal.\n"
        "  - If the job needs something the candidate does not have, leave it out. "
        "Do not stretch.\n\n"
        "OUTPUT: reply with ONE JSON object and nothing else (no prose, no code "
        "fence). Shape:\n"
        "{\n"
        '  "name": "candidate full name",\n'
        '  "contact": "one line: email | phone | location | links",\n'
        '  "summary": "2-4 sentence professional summary, keyword-matched",\n'
        '  "skills": ["skill", ...],\n'
        '  "experience": [ {"header": "Title, Company | Dates | Location", '
        '"bullets": ["achievement bullet", ...]}, ... ],\n'
        '  "education": ["line", ...],\n'
        '  "extra": [ {"heading": "Certifications", "lines": ["..."]} ],\n'
        '  "keywords_used": ["the posting keyword you worked in", ...]\n'
        "}\n"
        "Keep experience newest-first. 'extra' is optional (use [] if none). "
        "'keywords_used' lists the posting's terms you actually incorporated, so "
        "the candidate can see what changed. Output ONLY the JSON object."
    )


def run_tailor(resume_path, job_url):
    """Run Claude to produce the tailored-resume JSON; return the parsed dict.

    Uses ONLY Read (for the resume PDF) and WebFetch (for the posting) — no MCP
    write tools, because the worker itself posts the result back over the scoped
    token endpoint. Raises on a non-zero exit, a timeout, or output that is not
    the expected JSON object — we never save a half-parsed or empty resume.
    """
    prompt = build_tailor_prompt(resume_path, job_url)
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "text",
        "--allowedTools", "Read,WebFetch,WebSearch",
        "--permission-mode", "acceptEdits",
    ]
    if os.environ.get("CLAUDE_DANGEROUS") == "1":
        cmd.append("--dangerously-skip-permissions")
    try:
        proc = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeTimeout(f"tailor run exceeded {CLAUDE_TIMEOUT}s")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude exited non-zero while tailoring")
    text = proc.stdout.strip()
    if not text:
        raise RuntimeError("tailoring produced no output")
    return _parse_tailor_json(text)


def _parse_tailor_json(text):
    """Extract and parse the single JSON object from Claude's tailor output.

    Claude is told to output only JSON, but models sometimes wrap it in a code
    fence or add a stray sentence. We locate the outermost {...} and parse that,
    rather than trusting the whole string. Raises ValueError if no valid JSON
    object is found — a loud failure the task reports, never a silent empty save.
    """
    # Strip a ```json ... ``` fence if present.
    if "```" in text:
        # Take the content between the first pair of fences.
        parts = text.split("```")
        for part in parts:
            candidate = part
            if candidate.lstrip().lower().startswith("json"):
                candidate = candidate.lstrip()[4:]
            candidate = candidate.strip()
            if candidate.startswith("{"):
                text = candidate
                break
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"tailor output had no JSON object: {text[:200]}")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict) or not obj.get("name"):
        raise ValueError("tailor JSON is missing required fields (name)")
    return obj


def handle_tailor(task):
    """Tailor the task's lead: read resume + posting, build JSON, post it back.

    Downloads the owner's resume PDF (over HTTP, like the scan path), runs Claude
    to produce the tailored JSON, then posts it to the backend which builds the
    .docx. Every failure propagates to handle()'s error reporting; the temp PDF is
    always cleaned up.
    """
    tid = task["id"]
    token = task["token"]
    payload = task.get("payload") or {}
    lead_id = payload.get("lead_id")
    if not lead_id:
        raise RuntimeError("tailor task has no lead_id in its payload")

    # The lead's job URL is what we tailor against. The backend already refused to
    # create the task without one, but read it from the queue payload if present.
    job_url = (payload.get("job_url") or "").strip()

    if not task.get("has_resume_pdf"):
        raise RuntimeError(
            "This account has no resume yet. Upload a resume PDF in the app, "
            "then tailor a lead."
        )

    # Download the owner's resume to a temp file, tailor, then always clean up.
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix=f"tailor_task{tid}_")
    os.close(fd)
    try:
        download_resume_pdf(tid, tmp_path)
        # If the queue payload did not carry the job URL, fall back to fetching it
        # from the backend is unnecessary — the prompt needs a URL, so require it.
        if not job_url:
            raise RuntimeError("tailor task has no job URL to tailor against")
        resume = run_tailor(tmp_path, job_url)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    keywords = resume.get("keywords_used") or []
    save_tailored_resume(token, lead_id, job_url, keywords, resume)
    return (
        f"Tailored your resume for this job ({len(keywords)} keywords worked in). "
        "Download it on the lead, tweak if you like, then save it as a PDF to apply."
    )


def handle(task):
    """Process one task end to end, updating its status/result as it goes.

    Flow: mark running → make sure the OWNER's search profile exists (distilling
    their PDF once if needed) → run Claude with the task's write-token → mark
    done/error. A scan that times out after saving some leads is reported as a
    partial success ('done' with a note), not a scary error, because the worker
    API cannot see the owner's leads to count them here — so we rely on Claude's
    own reply plus the timeout note rather than a cross-user count.
    """
    tid = task["id"]
    token = task.get("token")
    if not token:
        # A task with no token cannot be attributed to an owner. Fail it loudly.
        set_task_status(tid, "error", "Task has no scoped token; cannot run safely.")
        print(f"[task {tid}] error: missing token")
        return

    set_task_status(tid, "running")
    try:
        if task["kind"] == "tailor":
            # Tailoring reads the resume PDF + the posting directly and posts a
            # .docx back — it does not use the search profile at all, so branch
            # before ensure_profile (which is only for scans).
            result = handle_tailor(task)
            set_task_status(tid, "done", result)
            print(f"[task {tid}] done: {result[:120]}")
            return
        # Resolve the owner's profile FIRST so a missing resume fails before we
        # burn a full Claude run. This can itself call Claude (to distill a PDF).
        profile = ensure_profile(task)
        result = run_claude(build_prompt(task, profile), token)
        set_task_status(tid, "done", result)
        print(f"[task {tid}] done: {result[:120]}")
    except ClaudeTimeout as e:
        # The scan saves leads as it goes, so a timeout may still have produced
        # real leads. We can't count them from here (no owner-scoped read on the
        # worker path), so report it honestly as a timeout that MAY have saved
        # some — the user sees their inbox for the truth. Still a 'done' note, not
        # an error, so any saved leads aren't hidden behind a scary failure.
        note = (f"The run hit the {CLAUDE_TIMEOUT}s limit. Any leads it saved "
                "before then are already in your inbox; check there.")
        set_task_status(tid, "done", note)
        print(f"[task {tid}] timeout: {note}")
    except Exception as e:  # noqa: BLE001 - report any other failure back to the UI
        set_task_status(tid, "error", str(e)[:4000])
        print(f"[task {tid}] error: {e}")


def main():
    """Poll forever, handling pending tasks oldest-first."""
    if not WORKER_SHARED_SECRET:
        raise SystemExit(
            "WORKER_SHARED_SECRET is not set. The worker cannot read the task "
            "queue without it. Set it to the same value as the server's "
            "WORKER_SHARED_SECRET env var, then start the worker again."
        )
    print(f"Job Scout worker up. API={API}  project={PROJECT_ROOT}")
    print("Waiting for tasks (press the dashboard buttons to create them)...")
    while True:
        try:
            queue = get_queue() or []
            for task in sorted(queue, key=lambda t: t["id"]):
                # A queue row can carry an 'error' marker (e.g. a task minted with
                # no token). Skip those defensively; they are not runnable.
                if task.get("error"):
                    print(f"[task {task.get('id')}] skipped: {task['error']}")
                    continue
                handle(task)
        except urllib.error.HTTPError as e:
            # A 403 here means the shared secret is wrong; a 503 means the server
            # has no secret set. Print the body so the misconfig is obvious.
            print(f"poll HTTP error {e.code}: {e.read().decode(errors='replace')[:300]}")
        except Exception as e:  # noqa: BLE001 - keep the loop alive on transient errors
            print("poll error:", e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
