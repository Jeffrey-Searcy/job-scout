"""
Token-authenticated API for the host-side worker (agent_worker.py).

Why this module is separate from views.py: the user-facing views authenticate a
logged-in person via a session cookie and scope everything to request.user. The
worker has NO login. It runs on the host, outside Docker, and serves ALL users'
searches from one shared queue. It therefore needs its own, clearly separated
way in — with two distinct credentials, each doing exactly one job:

  1. WORKER_SHARED_SECRET (a single long secret shared by server + worker):
     lets the worker READ the cross-user pending queue and POST distilled resume
     profiles back. This is the "trusted machine" credential. It never scopes a
     write to a user by itself.

  2. TaskToken (one per AgentTask, minted when the task is created): scopes each
     WRITE (add_lead / add_application) to that task's owner, and expires. This
     is what the MCP tools echo back so the API attributes a save to the right
     person. A leaked task token can only touch one task's writes, briefly.

Keeping these apart means a compromise of the queue-read secret still cannot
write to anyone's account, and a leaked task token cannot read the queue.

Every endpoint here opts OUT of the global SessionAuthentication/IsAuthenticated
defaults (AllowAny) and does its own credential check, because the caller is a
machine, not a browser session.
"""
import hmac

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AgentTask, JobLead, Resume, TaskToken, TailoredResume
from .serializers import JobApplicationSerializer, JobLeadSerializer

# How long a task's write-token stays valid, in seconds. Set comfortably past the
# worker's own run ceiling (CLAUDE_TIMEOUT, default 600s) so a slow but legitimate
# scan can still save its last lead, but not so long that a leaked token lingers.
# 20 minutes covers a 10-minute run with margin.
TASK_TOKEN_TTL_SECONDS = 20 * 60

# HTTP header names the worker/MCP use. Kept as constants so the worker, the MCP
# server, and this API never drift on spelling.
WORKER_SECRET_HEADER = "X-Worker-Secret"
TASK_TOKEN_HEADER = "X-Task-Token"


def _worker_secret_ok(request):
    """True only if the request carries the correct shared worker secret.

    Fail-closed: if WORKER_SHARED_SECRET is unset (empty), NO secret is accepted
    — we never default to an open queue. Uses hmac.compare_digest for a constant-
    time comparison so an attacker cannot learn the secret by timing responses.
    """
    configured = settings.WORKER_SHARED_SECRET
    if not configured:
        # Not configured → the worker path is closed. Caller returns 503.
        return False
    presented = request.headers.get(WORKER_SECRET_HEADER, "")
    return hmac.compare_digest(presented, configured)


def _worker_gate(request):
    """Check the worker secret; return an error Response if it fails, else None.

    Two distinct failures, reported honestly (no silent pass):
      - 503 when the server has no WORKER_SHARED_SECRET set (misconfiguration).
      - 403 when a secret is set but the caller's secret is wrong/missing.
    """
    if not settings.WORKER_SHARED_SECRET:
        return Response(
            {"detail": "Worker access is not configured (WORKER_SHARED_SECRET unset)."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not _worker_secret_ok(request):
        return Response(
            {"detail": "Bad or missing worker secret."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def resolve_task_token(request):
    """Return the valid TaskToken for this request, or None if it is not usable.

    Reads the X-Task-Token header, looks up the row, and checks it is unused and
    unexpired. Returns None on any miss (unknown/expired/used/missing) — the
    caller turns that into a 403. We deliberately do NOT distinguish the reasons
    to the caller, so a probe cannot map which tokens exist.
    """
    presented = request.headers.get(TASK_TOKEN_HEADER, "")
    if not presented:
        return None
    row = TaskToken.objects.filter(token=presented).select_related("owner", "task").first()
    if row is None or not row.is_valid():
        return None
    return row


class WorkerTasksView(APIView):
    """GET /api/worker/tasks/ — the cross-user pending queue for the worker.

    Authenticated by the shared worker secret only. Returns every PENDING task
    (all users), oldest-first, each already carrying what the worker needs to run
    it without any further per-user lookups:
      - token: the task's write-scoped TaskToken string.
      - profile: the OWNER's distilled resume search profile (may be empty if not
        distilled yet — the worker then distills from the PDF and posts it back).
      - resume_pdf_path: absolute path to the owner's uploaded PDF, or null.
    The worker never sees passwords or sessions; it sees only what a scan needs.
    """

    permission_classes = [AllowAny]  # gated by the shared secret instead

    def get(self, request):
        """Return pending tasks (all users) with per-task token + owner profile."""
        gate = _worker_gate(request)
        if gate is not None:
            return gate

        pending = (
            AgentTask.objects.filter(status=AgentTask.State.PENDING)
            .select_related("owner", "token_row")
            .order_by("id")
        )
        out = []
        for task in pending:
            token_row = getattr(task, "token_row", None)
            # A task with no token cannot be run safely (nothing scopes its
            # writes). Skip it loudly in the payload rather than handing the
            # worker a task it can't attribute. This should not happen — tasks
            # are always minted with a token — so surface it if it ever does.
            if token_row is None:
                out.append({
                    "id": task.id,
                    "error": "task has no token; cannot be dispatched",
                })
                continue
            resume = Resume.objects.filter(owner=task.owner).first()
            out.append({
                "id": task.id,
                "kind": task.kind,
                "payload": task.payload,
                "token": token_row.token,
                "profile": resume.profile if resume else "",
                # Whether the owner has a resume PDF the worker can distill. We do
                # NOT send a filesystem path: the worker runs on the host, outside
                # Docker, and the media volume only exists inside the containers.
                # When true, the worker downloads the PDF over HTTP from
                # /worker/tasks/<id>/resume.pdf (shared-secret gated) instead of
                # reading a path it cannot see.
                "has_resume_pdf": bool(resume and resume.pdf),
            })
        return Response(out)


class WorkerTaskUpdateView(APIView):
    """PATCH /api/worker/tasks/<id>/ — move a task through running → done/error.

    Authenticated by the shared worker secret. Accepts {status, result}. When the
    task reaches a terminal state (done/error) we mark its TaskToken used, so the
    write credential dies the moment the work is over — it cannot be replayed.
    """

    permission_classes = [AllowAny]  # gated by the shared secret instead

    def patch(self, request, pk):
        """Update one task's status/result; retire its token when it finishes."""
        gate = _worker_gate(request)
        if gate is not None:
            return gate

        new_status = request.data.get("status")
        valid = {s.value for s in AgentTask.State}
        if new_status not in valid:
            # Reject an unknown status loudly instead of writing garbage. Do this
            # before opening the transaction — nothing to write on a bad status.
            return Response(
                {"detail": f"status must be one of {sorted(valid)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update the task's state AND retire its token as one atomic unit, with a
        # row lock. Without this, a crash between the two writes (or two racing
        # PATCHes) could leave a terminal task with a still-live token until it
        # expires — exactly the leaked-credential window the token design exists
        # to prevent. select_for_update() serializes concurrent updates to the
        # same task; atomic() guarantees both writes commit together or neither.
        #
        # IMPORTANT: we lock ONLY the AgentTask row here — we do NOT
        # select_related("token_row"). token_row is a reverse OneToOne, so
        # select_related emits a LEFT OUTER JOIN, and Postgres refuses
        # "SELECT ... FOR UPDATE" on the nullable side of an outer join
        # (NotSupportedError: "FOR UPDATE cannot be applied to the nullable side
        # of an outer join"). That raised a 500 on every "running" PATCH. sqlite
        # ignores FOR UPDATE, so the earlier tests passed while Postgres broke.
        # We fetch the token with a separate, un-joined query inside the same
        # transaction — still atomic, still consistent.
        with transaction.atomic():
            task = (
                AgentTask.objects.select_for_update()
                .filter(pk=pk)
                .first()
            )
            if task is None:
                return Response(
                    {"detail": "No such task."}, status=status.HTTP_404_NOT_FOUND
                )

            task.status = new_status
            if "result" in request.data:
                task.result = request.data["result"][:4000]
            task.save(update_fields=["status", "result", "updated_at"])

            # Once the task is done or errored, retire its write-token in the same
            # transaction, so the token can never outlive the task's completion.
            # Separate query (no join) so the lock above stays on AgentTask only.
            if new_status in (AgentTask.State.DONE, AgentTask.State.ERROR):
                token_row = TaskToken.objects.filter(task=task).first()
                if token_row is not None and not token_row.used:
                    token_row.used = True
                    token_row.save(update_fields=["used"])

            return Response({"id": task.id, "status": task.status})


class WorkerResumeProfileView(APIView):
    """PUT /api/worker/tasks/<id>/profile/ — save a distilled profile for the owner.

    Authenticated by the shared worker secret. When a scan starts and the owner's
    resume has no distilled profile yet, the worker reads the PDF with Claude and
    posts the resulting profile text here. We store it on the OWNER's Resume so it
    is distilled once and reused by later scans. The task id names WHOSE profile to
    fill (the task's owner); the body carries {profile}.
    """

    permission_classes = [AllowAny]  # gated by the shared secret instead

    def put(self, request, pk):
        """Persist the distilled profile onto the task-owner's Resume."""
        gate = _worker_gate(request)
        if gate is not None:
            return gate

        task = AgentTask.objects.filter(pk=pk).select_related("owner").first()
        if task is None:
            return Response(
                {"detail": "No such task."}, status=status.HTTP_404_NOT_FOUND
            )
        profile = request.data.get("profile", "")
        if not profile or not profile.strip():
            # Never store an empty profile — that would make the scan hunt for no
            # one. Fail loudly so the worker reports the distillation problem.
            return Response(
                {"detail": "profile must be non-empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resume = Resume.objects.filter(owner=task.owner).first()
        if resume is None:
            # The owner deleted their resume between dispatch and now. Report it.
            return Response(
                {"detail": "Task owner has no resume to attach a profile to."},
                status=status.HTTP_409_CONFLICT,
            )
        resume.profile = profile.strip()
        resume.save(update_fields=["profile", "updated_at"])
        return Response({"task": task.id, "profile_ready": True})


class WorkerResumePdfView(APIView):
    """GET /api/worker/tasks/<id>/resume.pdf — stream the task owner's resume PDF.

    Authenticated by the shared worker secret. The worker runs on the host, where
    the Docker media volume does not exist, so it cannot read the PDF off disk.
    Instead it downloads the bytes here and distills them, then deletes its temp
    copy. Scoped to the task's OWNER: the id names whose resume, and the worker
    only ever gets the PDF for the task it is actually running.
    """

    permission_classes = [AllowAny]  # gated by the shared secret instead

    def get(self, request, pk):
        """Return the task-owner's resume PDF bytes, or 404 if there is none."""
        gate = _worker_gate(request)
        if gate is not None:
            return gate

        task = AgentTask.objects.filter(pk=pk).select_related("owner").first()
        if task is None:
            return Response(
                {"detail": "No such task."}, status=status.HTTP_404_NOT_FOUND
            )
        resume = Resume.objects.filter(owner=task.owner).first()
        if resume is None or not resume.pdf:
            # No PDF for this owner. The worker treats this as "no resume yet".
            return Response(
                {"detail": "Task owner has no resume PDF."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # FileResponse streams the file straight from storage; content type is
        # fixed since resume uploads are validated as PDFs on the way in.
        try:
            return FileResponse(
                resume.pdf.open("rb"), content_type="application/pdf"
            )
        except FileNotFoundError:
            # DB says there is a PDF but the file is gone — surface it, don't hide.
            raise Http404("Resume file is missing from storage.")


class _OwnerContext:
    """A minimal stand-in for a DRF request that carries just the owner user.

    The JobLead/JobApplication serializers scope their per-user dedup by reading
    ``context["request"].user``. On the session path that is the logged-in user.
    On the worker path there is no session, but the TaskToken names the owner —
    a real, authenticated User. We wrap that user so the SAME serializer logic
    runs unchanged and dedup stays correctly scoped to the token's owner.
    """

    def __init__(self, user):
        self.user = user


def _token_write(request, serializer_class):
    """Shared body for the worker's token-scoped create endpoints.

    Resolves the task token, then runs the given serializer with the owner taken
    FROM THE TOKEN (never from the request body), so the worker can only ever
    write to the account the token was minted for. Returns a DRF Response.
    """
    token_row = resolve_task_token(request)
    if token_row is None:
        # Unknown / expired / used / missing token — one honest 403, no hint as
        # to which. The worker's writes stop the moment its task's token dies.
        return Response(
            {"detail": "Bad, missing, or expired task token."},
            status=status.HTTP_403_FORBIDDEN,
        )
    owner = token_row.owner
    serializer = serializer_class(
        data=request.data, context={"request": _OwnerContext(owner)}
    )
    serializer.is_valid(raise_exception=True)
    # owner comes from the token, not the payload; read_only_fields=["owner"] on
    # the serializer already blocks any owner sent in the body.
    serializer.save(owner=owner)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


class WorkerLeadCreateView(APIView):
    """POST /api/worker/leads/ — add a scout lead, scoped by a task token.

    The MCP add_lead tool calls this with the task's X-Task-Token. The lead is
    saved to the TOKEN OWNER's inbox. All the normal JobLead validation and the
    per-user dedup run here, so a duplicate posting is rejected exactly as it is
    on the user path.
    """

    permission_classes = [AllowAny]  # gated by the task token instead

    def post(self, request):
        """Create a lead owned by the task token's owner."""
        return _token_write(request, JobLeadSerializer)


class WorkerApplicationCreateView(APIView):
    """POST /api/worker/applications/ — add an application, scoped by a task token.

    The MCP add_application tool (the 'enrich a link' flow) calls this with the
    task's X-Task-Token. The application is saved to the TOKEN OWNER's pipeline.
    """

    permission_classes = [AllowAny]  # gated by the task token instead

    def post(self, request):
        """Create an application owned by the task token's owner."""
        return _token_write(request, JobApplicationSerializer)


class WorkerTailoredResumeView(APIView):
    """POST /api/worker/tailored-resume/ — save a tailored resume, scoped by task token.

    The tailoring worker (agent_worker.py, 'tailor' task) calls this with the
    task's X-Task-Token after it has read the job posting and rewritten the base
    resume's wording. The body carries the structured resume content plus the
    target lead id and the keywords worked in:

        {
          "lead_id": <int>,
          "job_url": "<the posting the keywords came from>",
          "keywords": ["...", ...],
          "resume": { name, contact, summary, skills, experience, education, extra }
        }

    The backend (not the worker) turns ``resume`` into an ATS-safe .docx here,
    because python-docx and the media volume both live in the container. We save
    exactly one TailoredResume per lead: re-tailoring replaces the old file so a
    lead never accumulates stale drafts.

    Ownership is taken from the TASK TOKEN, never the body, and we verify the
    lead belongs to that same owner — so a leaked token can only ever write a
    tailored resume onto its own owner's lead.
    """

    permission_classes = [AllowAny]  # gated by the task token instead

    def post(self, request):
        """Build the .docx from the posted content and attach it to the lead."""
        # Import the builder lazily so a python-docx import problem surfaces on
        # THIS request (as a clear 500 the worker reports) rather than at module
        # load, which would take the whole worker API down.
        from .docx_builder import build_tailored_docx
        from django.core.files.base import ContentFile

        token_row = resolve_task_token(request)
        if token_row is None:
            return Response(
                {"detail": "Bad, missing, or expired task token."},
                status=status.HTTP_403_FORBIDDEN,
            )
        owner = token_row.owner

        lead_id = request.data.get("lead_id")
        resume_content = request.data.get("resume")
        if not lead_id or not isinstance(resume_content, dict):
            # A tailor with no lead or no content is unusable; refuse it loudly so
            # the worker reports the bad payload instead of writing an empty file.
            return Response(
                {"detail": "lead_id and a resume object are both required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # The lead MUST belong to the token's owner. This is the security check:
        # the token scopes the write, and we refuse to attach a tailored resume to
        # anyone else's lead even if the body names one.
        lead = JobLead.objects.filter(pk=lead_id, owner=owner).first()
        if lead is None:
            return Response(
                {"detail": "No such lead for this task's owner."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Build the Word document. build_tailored_docx raises loudly on a
        # malformed shape (e.g. no name), which we surface as a 400 rather than
        # saving a broken file.
        try:
            docx_bytes = build_tailored_docx(resume_content)
        except (KeyError, TypeError, ValueError) as e:
            return Response(
                {"detail": f"Tailored resume content was malformed: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        keywords = request.data.get("keywords") or []
        keywords_text = "\n".join(
            str(k).strip() for k in keywords if str(k).strip()
        )
        job_url = (request.data.get("job_url") or lead.url or "").strip()

        # One tailored resume per lead: update in place if it exists (replacing the
        # file), else create. update_or_create keeps the OneToOne invariant.
        tr, _created = TailoredResume.objects.update_or_create(
            lead=lead,
            defaults={
                "owner": owner,
                "job_url": job_url,
                "keywords": keywords_text,
            },
        )
        # Replace any previous file, then save the fresh .docx under the per-user
        # path. Delete-then-save avoids leaving an orphaned old file on re-tailor.
        if tr.docx:
            tr.docx.delete(save=False)
        filename = f"lead_{lead.id}.docx"
        tr.docx.save(filename, ContentFile(docx_bytes), save=True)

        return Response(
            {"lead_id": lead.id, "tailored_resume_id": tr.id},
            status=status.HTTP_201_CREATED,
        )
