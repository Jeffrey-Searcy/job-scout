"""
REST API views (API-first).

Endpoints:
  - /api/applications/         CRUD for pipeline applications
  - /api/leads/                CRUD for scout leads (+ /leads/{id}/promote/)
  - /api/agent-tasks/          create/list AI work requests (+ ?status= filter)
  - /api/stats/                pipeline summary for the dashboard
"""
from django.http import FileResponse, Http404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    JobApplication,
    JobLead,
    AgentTask,
    Resume,
    TaskToken,
)
from .serializers import (
    JobApplicationSerializer,
    JobLeadSerializer,
    AgentTaskSerializer,
    ResumeSerializer,
)
from .services import pipeline_stats


def mint_task_with_token(owner, kind, payload=None):
    """Create an AgentTask for ``owner`` plus its scoped write-token, atomically.

    Every task the UI creates needs exactly one TaskToken (see TaskToken): the
    token scopes the host worker's writes for THIS task back to THIS owner and
    expires past the run ceiling. Both the agent-tasks viewset (scan/enrich) and
    the lead "tailor" action create tasks, so the token-minting lives here in one
    place instead of being duplicated — a task must never exist without a token.

    Returns the created AgentTask.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .worker_api import TASK_TOKEN_TTL_SECONDS

    task = AgentTask.objects.create(owner=owner, kind=kind, payload=payload or {})
    TaskToken.objects.create(
        owner=owner,
        task=task,
        expires_at=timezone.now() + timedelta(seconds=TASK_TOKEN_TTL_SECONDS),
    )
    return task


class JobApplicationViewSet(viewsets.ModelViewSet):
    """Full CRUD for the CURRENT USER's pipeline, newest-applied first.

    get_queryset scopes every read/write to request.user, so one user can never
    see or touch another's applications. perform_create stamps the owner from
    the session, not from client input — the client cannot forge ownership.
    """

    serializer_class = JobApplicationSerializer

    def get_queryset(self):
        """Only the logged-in user's applications."""
        return JobApplication.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        """Set owner to the logged-in user on create."""
        serializer.save(owner=self.request.user)

    def get_serializer_context(self):
        """Pass the request into the serializer so it can build absolute URLs.

        The resume_file block needs the request to turn the relative download path
        into an absolute URL; DRF viewsets include the request by default, but we
        make it explicit here since a serializer method depends on it.
        """
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    @action(
        detail=True,
        methods=["post", "delete"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def resume(self, request, pk=None):
        """Attach, replace, or remove the resume submitted for this application.

        - POST   /api/applications/{id}/resume/  → attach or replace the file
          (multipart form field ``resume``; PDF or .docx). Replacing deletes the
          old file first so storage never accumulates orphans.
        - DELETE /api/applications/{id}/resume/  → remove the attached file.

        Scoped to the user's own applications (get_object filters by request.user).
        Bad or missing input fails loudly with a clear message — no silent no-op.
        """
        application = self.get_object()  # scoped to the user's own applications

        if request.method == "DELETE":
            if not application.resume:
                return Response(
                    {"detail": "This application has no attached resume to remove."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            application.resume.delete(save=False)
            application.resume = None
            application.save(update_fields=["resume", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)

        # POST: attach or replace.
        upload = request.FILES.get("resume")
        if upload is None:
            return Response(
                {"detail": "No file provided. Send the resume in the 'resume' form field."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Accept only the two formats the user actually submits: PDF (final) and
        # .docx (the tailored/editable form). Reject anything else loudly rather
        # than store a file that will confuse the record later.
        name = (upload.name or "").lower()
        if not (name.endswith(".pdf") or name.endswith(".docx")):
            return Response(
                {"detail": "The resume must be a .pdf or .docx file."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Cap the size (a resume is a few hundred KB; 5 MB is generous) so a huge
        # upload cannot fill the disk. Same limit as the base resume PDF.
        if upload.size > 5 * 1024 * 1024:
            return Response(
                {"detail": f"Resume is too large ({upload.size} bytes); limit is 5 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Replace cleanly: drop the old file before saving the new one so we never
        # leave an orphaned file in storage.
        if application.resume:
            application.resume.delete(save=False)
        application.resume.save(upload.name, upload, save=True)
        return Response(
            JobApplicationSerializer(application, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="resume/download")
    def resume_download(self, request, pk=None):
        """GET /api/applications/{id}/resume/download/ — download the attached resume.

        Login-gated and scoped to the user's own applications, exactly like the
        base resume PDF and the tailored .docx: the storage path is private and
        never served by nginx, so this endpoint is the only way to the bytes.
        404 if the application has no resume attached.
        """
        application = self.get_object()  # scoped to the user's own applications
        if not application.resume:
            return Response(
                {"detail": "This application has no attached resume."},
                status=status.HTTP_404_NOT_FOUND,
            )
        import os

        # Pick a content type from the extension so the browser handles it right.
        stored_name = application.resume.name
        ext = os.path.splitext(stored_name)[1].lower()
        content_type = (
            "application/pdf"
            if ext == ".pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        # A friendly download filename: <company>_<role>_resume<ext>.
        def safe(text):
            return "".join(ch if ch.isalnum() else "_" for ch in (text or "")).strip("_")

        base = f"{safe(application.company)}_{safe(application.role)}_resume" or "resume"
        filename = f"{base}{ext}"
        try:
            return FileResponse(
                application.resume.open("rb"),
                as_attachment=True,
                filename=filename,
                content_type=content_type,
            )
        except FileNotFoundError:
            # Row says there is a file but it is gone from storage — surface it.
            raise Http404("Attached resume file is missing from storage.")


class JobLeadViewSet(viewsets.ModelViewSet):
    """CRUD for the current user's scout leads, plus a 'promote' action.

    Scoped to request.user like applications. Promote works on a lead the user
    owns (get_object already filters by the scoped queryset), and the created
    application inherits that same owner via promote_to_application.
    """

    serializer_class = JobLeadSerializer

    def get_queryset(self):
        """Only the logged-in user's leads."""
        return JobLead.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        """Set owner to the logged-in user on create."""
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def promote(self, request, pk=None):
        """POST /api/leads/{id}/promote/ — create an application from this lead."""
        # get_object() is scoped to the user's leads, so you can only promote
        # a lead you own; the new application inherits your ownership.
        lead = self.get_object()
        application = lead.promote_to_application()
        return Response(JobApplicationSerializer(application).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def tailor(self, request, pk=None):
        """POST /api/leads/{id}/tailor/ — start building a keyword-matched resume.

        Creates a 'tailor' AgentTask (with its scoped write-token) that the host
        worker picks up. The worker reads THIS lead's real job posting and the
        user's base resume, then rewrites the wording to match the posting's true
        keywords — honestly, never inventing skills — and posts a .docx back.

        Preconditions, each failed loudly (no silent no-op):
          - the user must own the lead (get_object is already scoped),
          - the lead must have a job URL to read keywords from,
          - the user must have a base resume to tailor.

        Returns the created task so the UI can poll its progress with the same
        loading bar the scan uses. The finished resume then appears on the lead.
        """
        lead = self.get_object()  # scoped to the user's own leads

        # A tailor with no posting to read has no keywords to match — refuse it
        # rather than produce a resume tailored to nothing.
        if not (lead.url or "").strip():
            return Response(
                {"detail": "This lead has no job link, so there is nothing to tailor against."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # No base resume means nothing to rewrite. Point the user at uploading one.
        resume = Resume.objects.filter(owner=request.user).first()
        if resume is None or not resume.pdf:
            return Response(
                {"detail": "Upload your resume first, then tailor it to a job."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # payload carries which lead to tailor plus the posting URL, so the worker
        # can fetch the job and attribute the resulting .docx to the right lead
        # without any extra owner-scoped lookup on the worker path.
        task = mint_task_with_token(
            owner=request.user,
            kind=AgentTask.Kind.TAILOR,
            payload={"lead_id": lead.id, "job_url": lead.url},
        )
        return Response(AgentTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="tailored-resume")
    def tailored_resume(self, request, pk=None):
        """GET /api/leads/{id}/tailored-resume/ — download this lead's tailored .docx.

        Login-gated and scoped to the user's own leads (get_object filters by
        request.user), exactly like the resume-PDF download: the storage path is
        private and never served by nginx, so this is the only way to the bytes.
        404 if the lead has not been tailored yet.
        """
        lead = self.get_object()  # scoped to the user's own leads
        tr = getattr(lead, "tailored_resume", None)
        if tr is None or not tr.docx:
            return Response(
                {"detail": "This lead has no tailored resume yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # A friendly download filename: tailored_<company>_<lead>.docx (spaces →
        # underscores so browsers/servers don't mangle it).
        safe_company = "".join(
            ch if ch.isalnum() else "_" for ch in (lead.company or "resume")
        ).strip("_") or "resume"
        filename = f"tailored_{safe_company}_lead{lead.id}.docx"
        try:
            return FileResponse(
                tr.docx.open("rb"),
                as_attachment=True,
                filename=filename,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )
        except FileNotFoundError:
            # Row says there is a file but it is gone from storage — surface it.
            raise Http404("Tailored resume file is missing from storage.")


class AgentTaskViewSet(viewsets.ModelViewSet):
    """Create/list/update the current user's AI work requests.

    Scoped to request.user. Supports ?status=pending for polling. The host
    worker does NOT use this viewset to see everyone's tasks — a later layer
    gives the worker its own owner-agnostic, token-scoped access. Through this
    session-authenticated viewset, a user sees only their own tasks.
    """

    serializer_class = AgentTaskSerializer

    def get_queryset(self):
        """The logged-in user's tasks, optionally filtered by ?status=."""
        qs = AgentTask.objects.filter(owner=self.request.user)
        state = self.request.query_params.get("status")
        return qs.filter(status=state) if state else qs

    def perform_create(self, serializer):
        """Create the task for the logged-in user and mint its scoped token.

        Every task gets exactly one TaskToken (OneToOne). The token authorizes
        the host worker's writes for THIS task back to THIS owner, and expires a
        few minutes past the worker's own run ceiling so a leaked token cannot be
        replayed later. This viewset builds scan/enrich tasks from the UI; the
        lead "tailor" action builds tailor tasks the same way. Both go through
        mint_task_with_token so no task is ever created without a token.
        """
        from datetime import timedelta

        from django.utils import timezone

        from .worker_api import TASK_TOKEN_TTL_SECONDS

        task = serializer.save(owner=self.request.user)
        TaskToken.objects.create(
            owner=self.request.user,
            task=task,
            expires_at=timezone.now() + timedelta(seconds=TASK_TOKEN_TTL_SECONDS),
        )

    def perform_update(self, serializer):
        """Freeze a task's inputs after creation on the user path.

        A task's ``payload`` is set once, at create time (e.g. an enrich task's
        URL). There is no legitimate reason for the UI to rewrite it afterward,
        and letting it would let a user re-point a task the worker may already be
        running. ``status`` and ``result`` are already read-only on the
        serializer, so together this makes a task's inputs immutable to the user
        once created — only the worker changes its state.
        """
        serializer.save(payload=serializer.instance.payload)


class ResumeView(APIView):
    """The current user's resume: view status, upload/replace, or remove.

    - GET    /api/resume/  → the user's resume (404 if none uploaded yet).
    - PUT    /api/resume/  → upload or replace the PDF (multipart form field
                             ``pdf``). Replacing clears the distilled profile so
                             the worker re-distills from the new file.
    - DELETE /api/resume/  → remove the resume entirely.

    One resume per user (OneToOne), always scoped to request.user, so a user can
    only ever see or change their own.
    """

    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        """Return the current user's resume, or 404 if they have none."""
        resume = Resume.objects.filter(owner=request.user).first()
        if resume is None:
            return Response(
                {"detail": "No resume uploaded yet."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(ResumeSerializer(resume, context={"request": request}).data)

    def put(self, request):
        """Upload or replace the user's resume PDF.

        On replace we clear ``profile`` so a stale profile from the old resume is
        never reused — the worker distills the new PDF on the next scan.
        """
        resume = Resume.objects.filter(owner=request.user).first()
        serializer = ResumeSerializer(
            instance=resume, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        # Blank the profile on every (re)upload so the worker re-distills. owner
        # comes from the session, never the client.
        serializer.save(owner=request.user, profile="")
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request):
        """Remove the current user's resume (and its file)."""
        resume = Resume.objects.filter(owner=request.user).first()
        if resume is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        # Delete the file from storage, then the row.
        resume.pdf.delete(save=False)
        resume.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResumePdfView(APIView):
    """GET /api/resume/pdf/ — download the CURRENT USER's own resume PDF.

    This is the ONLY way a browser gets resume bytes. We deliberately do NOT let
    nginx serve /media/ resumes directly, because that would have no login check
    and the file URLs are guessable (resumes/user_<id>/<file>). Here the file is
    scoped to request.user: you can only ever fetch your own resume, and only
    while logged in (the global IsAuthenticated default applies).
    """

    def get(self, request):
        """Stream the logged-in user's resume PDF, or 404 if they have none."""
        resume = Resume.objects.filter(owner=request.user).first()
        if resume is None or not resume.pdf:
            return Response(
                {"detail": "No resume uploaded yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            return FileResponse(
                resume.pdf.open("rb"), content_type="application/pdf"
            )
        except FileNotFoundError:
            # DB row exists but the file is gone — surface it rather than hide it.
            raise Http404("Resume file is missing from storage.")


class StatsView(APIView):
    """GET /api/stats/ — pipeline metrics for the dashboard tiles and funnel."""

    def get(self, request):
        """Return the logged-in user's pipeline stats as JSON."""
        return Response(pipeline_stats(request.user))
