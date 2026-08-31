"""DRF serializers: translate model instances to/from JSON for the REST API."""
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.utils import timezone
from rest_framework import serializers

from .models import (
    JobApplication,
    JobLead,
    AgentTask,
    Resume,
    Status,
    LeadStatus,
)


# Query-string keys that are tracking/routing noise, NOT part of a job's identity.
# Two URLs that differ only by these point at the same posting, so we drop them
# before comparing. Greenhouse re-appends ``gh_jid`` (the same id already in the
# path) and boards add utm_* / ref / source tags — none change which job it is.
_TRACKING_PARAMS = {
    "gh_jid",
    "gh_src",
    "ref",
    "source",
    "src",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}


# The most LIVE leads (status new/reviewed) one company may hold in the inbox at
# once. A hot company (e.g. Twilio) can otherwise post many matching roles and
# flood the inbox, drowning out other companies. Past this count, a scan's extra
# roles from that company are refused — the ones already there stay untouched, and
# dismissing/applying to some frees room for new ones. Set here so it is easy to
# tune in one place.
MAX_LIVE_LEADS_PER_COMPANY = 2


def normalize_job_url(raw):
    """Reduce a job-posting URL to a stable identity for duplicate comparison.

    The scout often re-surfaces the SAME posting with a slightly different URL —
    a tracking query added (``?gh_jid=...``, ``?utm_...``), a trailing slash, or a
    different host casing. Those variants are the same job, so an exact string
    match wrongly treats them as new. This collapses a URL to a canonical form so
    the same posting always compares equal:

      - lower-case the scheme and host (case-insensitive by spec),
      - drop a trailing slash on the path,
      - remove known tracking query params, keep any that remain (sorted so order
        never matters), and
      - drop the fragment (``#...``), which never identifies a posting.

    Returns "" for an empty/blank input so callers can skip the check cleanly.
    We deliberately do NOT strip ALL query params — some boards put the real job
    id in the query (e.g. ``?jobId=123``), and dropping that would merge two
    different jobs into one. Only the known-noise keys above are removed.
    """
    url = (raw or "").strip()
    if not url:
        return ""
    parts = urlparse(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # Normalize the path: drop a single trailing slash so ".../123" and ".../123/"
    # match, but keep "/" itself intact.
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # Keep only the meaningful query params, sorted for order-independence.
    kept = [(k, v) for (k, v) in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS]
    query = urlencode(sorted(kept))
    # Fragments never identify a posting; drop them.
    return urlunparse((scheme, netloc, path, parts.params, query, ""))


class JobApplicationSerializer(serializers.ModelSerializer):
    """Serializes a JobApplication, adding computed display fields for the UI.

    Adds a read-only ``resume_file`` block so the pipeline card can show whether a
    resume is attached and give a login-gated download link for it. The block is
    null until the user attaches a file. The raw ``resume`` FileField is read-only
    through this serializer — attaching happens only through the dedicated
    multipart upload endpoint (see JobApplicationViewSet.resume), never via a JSON
    PATCH, so a caller cannot point an application at an arbitrary stored file.
    """

    salary_display = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    resume_file = serializers.SerializerMethodField()

    class Meta:
        model = JobApplication
        fields = "__all__"
        # owner is set server-side from the session (perform_create), never from
        # client JSON. resume is read-only here so no JSON create/PATCH can set,
        # change, or clear the attached file — that happens ONLY through the
        # dedicated multipart upload endpoint (JobApplicationViewSet.resume). A
        # stray {"resume": ...} in a status-change PATCH is therefore ignored, not
        # allowed to wipe the attachment.
        read_only_fields = ["owner", "resume"]

    def to_representation(self, instance):
        """Serialize the application, hiding the raw resume storage path.

        The raw ``resume`` FileField value is the private /media/ path, which nginx
        never serves. The UI reads the attachment only through the safe
        ``resume_file`` block (filename + login-gated download URL), so we drop the
        raw field from the output entirely — mirroring how ResumeSerializer keeps
        the base resume PDF path out of its JSON.
        """
        data = super().to_representation(instance)
        data.pop("resume", None)
        return data

    def get_resume_file(self, obj):
        """Return the attached resume's summary, or None if none is attached.

        We never expose the raw storage path (private, like the resume PDF and the
        tailored resume). Instead we hand back the original filename and the
        login-gated download URL, so the card can render a "Resume attached"
        download link. Returns None when no file is attached.
        """
        if not obj.resume:
            return None
        request = self.context.get("request")
        path = f"/api/applications/{obj.id}/resume/"
        download_url = request.build_absolute_uri(path) if request else path
        # obj.resume.name is the stored path; show just the base filename to the UI.
        import os

        return {
            "filename": os.path.basename(obj.resume.name),
            "download_url": download_url,
            "updated_at": obj.updated_at,
        }

    def validate(self, attrs):
        """Default applied_date to today when a new application lacks one.

        Every create path (the enrich flow behind "Add from link", the MCP tool,
        a manual add) runs through here, so filing a job you've applied to always
        gets a date to sort by — without the caller having to remember to set it.
        We only fill it on create (self.instance is None) and never overwrite a
        date the user typed. A row explicitly created as a lead you haven't applied
        to yet still gets today's date, which is the sensible "filed on" stamp.
        """
        if self.instance is None and not attrs.get("applied_date"):
            attrs["applied_date"] = timezone.localdate()
        return attrs


class JobLeadSerializer(serializers.ModelSerializer):
    """Serializes a JobLead (scout inbox item).

    Adds a read-only ``tailored_resume`` block so the inbox UI can show whether a
    lead already has a keyword-matched resume, and give a download link for it.
    The block is null until the user tailors that lead.
    """

    tailored_resume = serializers.SerializerMethodField()

    class Meta:
        model = JobLead
        fields = "__all__"
        # owner is set server-side from the session/task token, never from
        # client JSON — read-only here so a caller cannot assign a lead away.
        read_only_fields = ["owner"]

    def get_tailored_resume(self, obj):
        """Return the lead's tailored-resume summary, or None if it has none.

        We never expose the raw storage path (private, like the resume PDF).
        Instead we hand back the login-gated download URL and the keyword list, so
        the UI can render a "Download tailored resume" link plus show which
        keywords were worked in. Uses the OneToOne reverse accessor guarded for
        absence — a lead usually has no tailored resume.
        """
        tr = getattr(obj, "tailored_resume", None)
        if tr is None or not tr.docx:
            return None
        request = self.context.get("request")
        # Build the absolute, login-gated download URL for this lead's docx.
        path = f"/api/leads/{obj.id}/tailored-resume/"
        download_url = request.build_absolute_uri(path) if request else path
        return {
            "id": tr.id,
            "download_url": download_url,
            "job_url": tr.job_url,
            # Keywords are stored newline-separated; hand the UI a clean list.
            "keywords": [k for k in (tr.keywords or "").splitlines() if k.strip()],
            "created_at": tr.created_at,
            "updated_at": tr.updated_at,
        }

    def validate(self, attrs):
        """Reject a lead for a posting already in THIS OWNER's pipeline or inbox.

        The scout can otherwise re-surface a role the candidate has already
        applied to (or already has queued), because the model's own uniqueness
        only compares leads to other leads. We match on the apply URL, which is
        the stable identity of a posting. A URL tied only to a rejected/ghosted
        application is allowed through — re-surfacing a dead role is fine.

        The dedup is scoped to the lead's owner: another user holding the same
        posting must not block this user's lead. The owner is resolved from the
        serializer context (set by perform_create / the worker's token auth),
        falling back to the payload's owner when present. Creates only; updates
        (self.instance set) skip the check.
        """
        if self.instance is not None:
            return attrs
        url = (attrs.get("url") or "").strip()
        if not url:
            return attrs  # No URL to match on; nothing to dedupe against.

        # Whose inbox/pipeline are we deduping against? The view stamps owner on
        # create via perform_create(owner=request.user); until save() runs it is
        # not yet in attrs, so read it from the request user in context.
        request = self.context.get("request")
        owner = getattr(request, "user", None)
        if owner is None or not owner.is_authenticated:
            # No owner in context means we cannot scope the check safely. Rather
            # than dedupe against the whole table (cross-user leak) or skip the
            # check silently, fail loudly — this path should never happen for a
            # normal authenticated create.
            raise serializers.ValidationError(
                {"detail": "Cannot create a lead without a resolved owner."}
            )

        # Compare on the NORMALIZED URL, not the raw string. The scout re-surfaces
        # the same posting with tracking junk added (e.g. Greenhouse appends
        # ?gh_jid=), so an exact DB match misses real duplicates. We normalize the
        # incoming URL once, then normalize each of the owner's candidate rows and
        # compare. The candidate sets are small (one user's own pipeline/inbox),
        # so pulling them and comparing in Python is cheap and correct — a raw SQL
        # equality could never see past the tracking suffix.
        target = normalize_job_url(url)

        # Already an active application for this posting, for this owner?
        for app in (
            JobApplication.objects.filter(owner=owner)
            .exclude(status__in=[Status.REJECTED, Status.GHOSTED])
            .exclude(link="")
        ):
            if normalize_job_url(app.link) == target:
                raise serializers.ValidationError(
                    {"url": f"Already in your pipeline as an application "
                            f"(#{app.id}, status '{app.status}'). Not re-added."}
                )

        # Already a live lead for this posting for this owner (ignore dismissed)?
        for lead in (
            JobLead.objects.filter(owner=owner)
            .exclude(status=LeadStatus.DISMISSED)
            .exclude(url="")
        ):
            if normalize_job_url(lead.url) == target:
                raise serializers.ValidationError(
                    {"url": f"Already in your scout inbox (lead #{lead.id}). Not re-added."}
                )

        # Per-company cap: refuse a new lead when this company already fills the
        # inbox with MAX_LIVE_LEADS_PER_COMPANY live leads. "Live" = not dismissed
        # and not already applied, so dismissing or applying to some makes room.
        # Matched case-insensitively because the scanner's capitalization varies
        # ("Twilio" vs "twilio"). This runs only on create and only when a company
        # name is present; the URL dedup above has already cleared exact repeats.
        company = (attrs.get("company") or "").strip()
        if company:
            live_for_company = (
                JobLead.objects.filter(owner=owner, company__iexact=company)
                .exclude(status=LeadStatus.DISMISSED)
                .exclude(status=LeadStatus.APPLIED)
                .count()
            )
            if live_for_company >= MAX_LIVE_LEADS_PER_COMPANY:
                raise serializers.ValidationError(
                    {"company": f"Your inbox already has {live_for_company} live "
                                f"leads from {company} (cap is {MAX_LIVE_LEADS_PER_COMPANY}). "
                                f"Dismiss or apply to some before adding more."}
                )
        return attrs


class AgentTaskSerializer(serializers.ModelSerializer):
    """Serializes an AgentTask (AI work request + its status/result).

    ``status`` and ``result`` are worker-owned: only the host worker moves a task
    through running → done/error and writes its result, via the separate worker
    API (worker_api.py, which does raw model writes, not this serializer). We mark
    them read-only here so a logged-in user cannot PATCH their own task straight
    to "done" (which would hide it from the worker's pending queue and leave its
    write-token live until it expires) or overwrite the worker's result text.
    ``payload`` is settable on create (an enrich task carries its URL) but frozen
    on update — see AgentTaskViewSet.perform_update.
    """

    class Meta:
        model = AgentTask
        fields = "__all__"
        # owner comes from the session; status/result are written only by the
        # worker. None of these are accepted from the user's JSON.
        read_only_fields = ["owner", "status", "result"]


# Max resume upload size. A resume PDF is a few hundred KB; 5 MB is generous and
# stops someone from filling the disk with a huge upload. Enforced in validate.
MAX_RESUME_BYTES = 5 * 1024 * 1024


class ResumeSerializer(serializers.ModelSerializer):
    """Serializes a user's Resume: the uploaded PDF + distilled profile status.

    ``pdf`` is WRITE-ONLY: you upload it, but the response never echoes its
    storage URL. That path (/media/resumes/user_<id>/…) is private and no longer
    served by nginx — the only way to read the bytes back is the auth-gated
    /api/resume/pdf/ endpoint. ``profile`` is read-only here (the worker fills
    it). ``profile_ready`` lets the UI show whether a scan can use the resume yet.
    """

    profile_ready = serializers.BooleanField(read_only=True)
    # Accept the upload but never return the file URL in JSON — the storage path
    # is private and unguessable-by-design; reads go through /api/resume/pdf/.
    pdf = serializers.FileField(write_only=True)

    class Meta:
        model = Resume
        fields = ["id", "pdf", "profile", "profile_ready", "created_at", "updated_at"]
        # owner comes from the session; profile is worker-written; timestamps and
        # the distilled profile are never set by the uploading client.
        read_only_fields = ["id", "profile", "profile_ready", "created_at", "updated_at"]

    def validate_pdf(self, value):
        """Accept only a real PDF within the size limit; fail loudly otherwise.

        We check both the content type the browser reports and the filename
        extension, and cap the size. No silent acceptance of non-PDFs — a wrong
        file would just make the later resume-distill step fail confusingly.
        """
        name = (getattr(value, "name", "") or "").lower()
        content_type = getattr(value, "content_type", "") or ""
        if not name.endswith(".pdf"):
            raise serializers.ValidationError("The resume must be a .pdf file.")
        if content_type and content_type != "application/pdf":
            raise serializers.ValidationError(
                f"Expected a PDF but got content type '{content_type}'."
            )
        if value.size > MAX_RESUME_BYTES:
            raise serializers.ValidationError(
                f"Resume is too large ({value.size} bytes); limit is {MAX_RESUME_BYTES}."
            )
        return value
