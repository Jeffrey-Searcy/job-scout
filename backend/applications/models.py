"""
Database models for the job search.

Two core entities:
  - JobApplication: a role you have actually applied to (your pipeline).
  - JobLead: a role surfaced by the scout that you have NOT yet applied to
             (an inbox you triage; promote good ones into JobApplication).
"""
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


class JobApplication(TimestampedModel):
    """A single application in the pipeline (one row per role applied to)."""

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
    """A role discovered by the scout, pending your review (the leads inbox)."""

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
        # Prevent the scout from inserting the same posting twice.
        constraints = [
            models.UniqueConstraint(fields=["company", "title", "url"], name="uniq_lead")
        ]

    def __str__(self):
        """Human-readable label."""
        return f"[lead] {self.company} — {self.title}"

    def promote_to_application(self):
        """Create a JobApplication from this lead and mark the lead as applied.

        Returns the newly created JobApplication so callers can inspect it.
        """
        application = JobApplication.objects.create(
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

    class State(models.TextChoices):
        """Lifecycle of a task as the worker processes it."""

        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        ERROR = "error", "Error"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    payload = models.JSONField(default=dict, blank=True, help_text="Task inputs, e.g. {'url': ..., 'status': ...}.")
    status = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    result = models.TextField(blank=True, help_text="Human-readable summary the worker writes back.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """Label for admin/logs."""
        return f"{self.kind} [{self.status}] #{self.pk}"
