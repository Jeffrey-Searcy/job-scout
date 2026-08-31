"""
Database models for the job search.

Two core entities:
  - JobApplication: a role you have actually applied to (your pipeline).
  - JobLead: a role surfaced by the scout that you have NOT yet applied to
             (an inbox you triage; promote good ones into JobApplication).
"""
from django.conf import settings
from django.db import models


class Status(models.TextChoices):
    """Pipeline stages an application can move through, in rough order."""

    APPLIED = "applied", "Applied"
    PHONE_SCREEN = "phone_screen", "Phone screen"
    INTERVIEW = "interview", "Interview"
    TAKE_HOME = "take_home", "Take-home"
    ONSITE = "onsite", "Onsite"
    OFFER = "offer", "Offer"
    REJECTED = "rejected", "Rejected"
    GHOSTED = "ghosted", "Ghosted"


class WorkMode(models.TextChoices):
    """Where the work happens; drives the 'local hybrid/onsite' preference."""

    ONSITE = "onsite", "Onsite"
    HYBRID = "hybrid", "Hybrid"
    REMOTE = "remote", "Remote"
    UNKNOWN = "unknown", "Unknown"


class Fit(models.TextChoices):
    """Subjective match rating used for sorting and filtering."""

    STRONG = "strong", "Strong fit"
    GOOD = "good", "Good fit"
    STRETCH = "stretch", "Stretch"


class TimestampedModel(models.Model):
    """Abstract base adding created/updated timestamps to any model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def application_resume_upload_path(instance, filename):
    """Store the resume attached to ONE application under its owner's folder.

    Path: application_resumes/user_<id>/app_<appid>_<file>. Mirrors the resume and
    tailored-resume paths: one folder per user makes ownership obvious on disk, and
    the application id in the name shows which job the file was submitted for. The
    file is served only through the login-gated download endpoint, never by nginx
    directly (same privacy rule as the base resume PDF).
    """
    return f"application_resumes/user_{instance.owner_id}/app_{instance.id}_{filename}"


class JobApplication(TimestampedModel):
    """A single application in the pipeline (one row per role applied to).

    ``owner`` scopes every application to one user. Each person sees only their
    own pipeline; the views filter on request.user. A one-time data migration
    assigns pre-existing rows (from the single-user era) to the first user.

    ``resume`` optionally holds the exact resume file the user submitted for this
    role (PDF or .docx). It is attached manually after applying, so the pipeline
    keeps a record of which resume went with which application — useful if a
    question comes up later, or to compare what was sent across roles.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    company = models.CharField(max_length=200)
    role = models.CharField(max_length=200)
    source = models.CharField(max_length=100, blank=True)
    link = models.URLField(max_length=1000, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.APPLIED)
    work_mode = models.CharField(max_length=10, choices=WorkMode.choices, default=WorkMode.UNKNOWN)
    location = models.CharField(max_length=200, blank=True)
    is_local = models.BooleanField(default=False)

    # Salary stored structured (dollars) so it can be sorted/filtered; either
    # bound may be null when a posting lists no range.
    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)

    fit = models.CharField(max_length=10, choices=Fit.choices, default=Fit.GOOD)
    angle = models.CharField(max_length=200, blank=True)
    contact = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True)

    applied_date = models.DateField(null=True, blank=True)
    followup_date = models.DateField(null=True, blank=True)

    # The resume actually submitted for this role (PDF or .docx). Blank until the
    # user attaches one. Stored under MEDIA_ROOT/application_resumes/user_<id>/...
    # and served only via the login-gated download view, never by nginx directly.
    resume = models.FileField(
        upload_to=application_resume_upload_path, blank=True, null=True
    )

    class Meta:
        ordering = ["-applied_date", "company"]

    def __str__(self):
        """Human-readable label used in the admin and logs."""
        return f"{self.company} — {self.role}"

    @property
    def salary_display(self):
        """Format the salary bounds as a compact human string (e.g. '$146K–206K')."""
        def k(v):
            return f"${v // 1000}K"

        if self.salary_min and self.salary_max:
            return f"{k(self.salary_min)}–{k(self.salary_max)}"
        if self.salary_min:
            return f"{k(self.salary_min)}+"
        return ""

    @property
    def is_active(self):
        """True when the application has advanced beyond the initial 'Applied' state."""
        return self.status not in (Status.APPLIED, Status.REJECTED, Status.GHOSTED)


class LeadStatus(models.TextChoices):
    """Triage states for scout-discovered leads."""

    NEW = "new", "New"
    REVIEWED = "reviewed", "Reviewed"
    DISMISSED = "dismissed", "Dismissed"
    APPLIED = "applied", "Applied"


class JobLead(TimestampedModel):
    """A role discovered by the scout, pending your review (the leads inbox).

    ``owner`` scopes each lead to one user, so the scout's finds land in that
    person's inbox only. The uniqueness rule includes owner, so the same
    posting can appear in two different users' inboxes independently.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="leads",
    )
    company = models.CharField(max_length=200)
    title = models.CharField(max_length=200)
    url = models.URLField(max_length=1000, blank=True)
    location = models.CharField(max_length=200, blank=True)
    work_mode = models.CharField(max_length=10, choices=WorkMode.choices, default=WorkMode.UNKNOWN)
    salary_text = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=100, blank=True)
    summary = models.TextField(blank=True, help_text="One-line why-it-fits from the scout.")
    is_local = models.BooleanField(default=False)

    discovered_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=LeadStatus.choices, default=LeadStatus.NEW)

    class Meta:
        ordering = ["-discovered_date", "-created_at"]
        # Prevent the scout from inserting the same posting twice FOR ONE USER.
        # owner is part of the key, so two users can each hold the same posting.
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "company", "title", "url"], name="uniq_lead"
            )
        ]

    def __str__(self):
        """Human-readable label."""
        return f"[lead] {self.company} — {self.title}"

    def promote_to_application(self):
        """Create a JobApplication from this lead and mark the lead as applied.

        Returns the newly created JobApplication so callers can inspect it.
        """
        application = JobApplication.objects.create(
            owner=self.owner,  # the promoted application belongs to the lead's owner
            company=self.company,
            role=self.title,
            source=self.source or "Scout",
            link=self.url,
            work_mode=self.work_mode,
            location=self.location,
            is_local=self.is_local,
            angle=self.summary[:200],
            notes=self.summary,
            status=Status.APPLIED,
        )
        self.status = LeadStatus.APPLIED
        self.save(update_fields=["status", "updated_at"])
        return application


def resume_upload_path(instance, filename):
    """Store each user's resume under its own folder: resumes/user_<id>/<file>.

    Keeping one folder per user makes ownership obvious on disk and avoids
    filename collisions between users who both upload "resume.pdf".
    """
    return f"resumes/user_{instance.owner_id}/{filename}"


def make_task_token():
    """Return a fresh, unguessable token string for a task's worker auth.

    Uses secrets.token_urlsafe for cryptographic randomness. Stored on the token
    row and handed to the worker; the MCP tools echo it back so the API can
    attribute their writes to the right owner. Not a password — it authorizes
    exactly one task's writes and expires (see TaskToken).
    """
    import secrets

    return secrets.token_urlsafe(32)


class TaskToken(models.Model):
    """A scoped, expiring credential that lets the worker write for ONE task.

    Why this exists: the host worker runs Claude, which calls the MCP tools to
    save found jobs. Those tools have no login session. Instead of giving the
    worker a user's password (dangerous, reusable), each AgentTask mints one of
    these. Its guarantees:

      - Scoped: it authorizes writes for exactly one owner and one task. A save
        made with it is attributed to ``owner`` — the worker cannot write to
        anyone else's account.
      - Single-task: it is tied to one AgentTask. When that task finishes
        (done/error) the token is marked used and stops working.
      - Expiring: it is only valid until ``expires_at`` (a few minutes past the
        task's own timeout), so a leaked token cannot be replayed later.

    It is NOT a general API key: it cannot log in, list data, or act outside its
    one task's writes.
    """

    token = models.CharField(max_length=64, unique=True, default=make_task_token)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_tokens",
    )
    task = models.OneToOneField(
        "AgentTask",
        on_delete=models.CASCADE,
        related_name="token_row",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    # Set true once the task completes; a used token no longer authorizes writes.
    used = models.BooleanField(default=False)

    def __str__(self):
        """Label for admin/logs (never prints the secret token itself)."""
        return f"token for task #{self.task_id} ({self.owner})"

    def is_valid(self):
        """True only if the token is unused and not yet expired.

        Import timezone locally to keep the module import list unchanged; called
        on the hot path of every worker-side write.
        """
        from django.utils import timezone

        return (not self.used) and self.expires_at > timezone.now()


class Resume(TimestampedModel):
    """One user's uploaded resume plus the search profile distilled from it.

    Each user has at most one active resume (OneToOne). The uploaded PDF is
    stored under MEDIA_ROOT in a per-user path. ``profile`` is the short text
    the scout actually searches with — filled in by the worker once, by reading
    the PDF with Claude Code (see the worker's distill step). It starts blank on
    upload and is populated asynchronously, so ``profile_ready`` tells the UI
    whether a scan can use it yet.
    """

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="resume",
    )
    # Stored under MEDIA_ROOT/resumes/user_<id>/<filename>. Kept out of git via
    # the media dir being gitignored; a user's real resume never ships.
    pdf = models.FileField(upload_to=resume_upload_path)
    # The distilled 5-8 sentence search profile. Blank until the worker fills it.
    profile = models.TextField(
        blank=True,
        help_text="Search profile distilled from the PDF; filled by the worker.",
    )

    def __str__(self):
        """Label for admin/logs."""
        return f"Resume for {self.owner}"

    @property
    def profile_ready(self):
        """True once the resume has been distilled into a usable search profile."""
        return bool(self.profile.strip())


def tailored_resume_upload_path(instance, filename):
    """Store each tailored resume under its owner's folder, keyed by lead.

    Path: tailored/user_<id>/lead_<leadid>_<file>. One folder per user keeps
    ownership obvious on disk (mirrors resume_upload_path), and putting the lead
    id in the name makes it easy to see which job a file was built for. The file
    itself is only ever served through the login-gated download endpoint, never
    by nginx directly (same rule as the resume PDF).
    """
    return f"tailored/user_{instance.owner_id}/lead_{instance.lead_id}_{filename}"


class TailoredResume(TimestampedModel):
    """A resume tailored to ONE job lead's real posting, saved as a .docx.

    Why this exists: the same base resume rarely matches every job's keywords, and
    many employers screen with an ATS (applicant tracking system) that ranks
    resumes by keyword before a human reads them. The user clicks "Tailor resume"
    on a lead; the host worker reads that job's real posting and the user's base
    resume, then rewrites the WORDING to use the job's true keywords — honestly,
    never inventing skills. The backend turns that text into a Word document and
    stores it here, attached to the lead.

    Lifecycle: created empty-ish when the tailor task starts is NOT done — instead
    the row is created only once the worker posts finished content back, so a row
    always has a real file. One tailored resume per lead (OneToOne): re-tailoring a
    lead replaces its file rather than piling up drafts. ``owner`` scopes it to one
    user for the login-gated download, and is redundant-but-explicit alongside the
    lead's own owner so the download query can filter on request.user directly.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tailored_resumes",
    )
    # One tailored resume per lead. Re-tailoring replaces the file (see the worker
    # write endpoint), so a lead never accumulates stale drafts.
    lead = models.OneToOneField(
        "JobLead",
        on_delete=models.CASCADE,
        related_name="tailored_resume",
    )
    # The finished Word document, stored under MEDIA_ROOT/tailored/user_<id>/...
    # Served only via the login-gated download view, never by nginx directly.
    docx = models.FileField(upload_to=tailored_resume_upload_path)
    # The exact job URL the worker read to tailor this resume. Recorded so the
    # user can see which posting the keywords came from, and so a re-tailor knows
    # what it matched against.
    job_url = models.URLField(max_length=1000, blank=True)
    # The keywords the worker pulled from the posting and worked into the resume,
    # newline-separated. Shown to the user so they can see WHY the wording changed
    # and spot anything that reads as a stretch before they submit.
    keywords = models.TextField(
        blank=True,
        help_text="Job-posting keywords the tailoring worked in, one per line.",
    )

    def __str__(self):
        """Label for admin/logs."""
        return f"Tailored resume for lead #{self.lead_id} ({self.owner})"


class AgentTask(TimestampedModel):
    """A unit of AI work requested from the UI and fulfilled by a host-side worker.

    The dashboard buttons create one of these (a 'scan' or an 'enrich' from a
    pasted link). A small worker on the host running Claude Code (logged into the
    Max plan) picks it up, does the model work, writes results back through the
    API/MCP, and marks the task done. The Dockerized app never runs the model
    itself — it only records the request and shows the outcome.
    """

    class Kind(models.TextChoices):
        """What kind of work the task represents."""

        SCAN = "scan", "Scan for jobs"
        ENRICH = "enrich", "Enrich a link"
        # Build a keyword-matched resume for one lead's real posting (see
        # TailoredResume). The task payload carries {'lead_id': <id>}.
        TAILOR = "tailor", "Tailor resume for a lead"

    class State(models.TextChoices):
        """Lifecycle of a task as the worker processes it."""

        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        ERROR = "error", "Error"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_tasks",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    payload = models.JSONField(default=dict, blank=True, help_text="Task inputs, e.g. {'url': ..., 'status': ...}.")
    status = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    result = models.TextField(blank=True, help_text="Human-readable summary the worker writes back.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """Label for admin/logs."""
        return f"{self.kind} [{self.status}] #{self.pk}"
