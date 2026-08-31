"""URL routing for the applications API (DRF router + the stats endpoint)."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    JobApplicationViewSet,
    JobLeadViewSet,
    AgentTaskViewSet,
    ResumeView,
    ResumePdfView,
    StatsView,
)
from .worker_api import (
    WorkerTasksView,
    WorkerTaskUpdateView,
    WorkerResumeProfileView,
    WorkerResumePdfView,
    WorkerLeadCreateView,
    WorkerApplicationCreateView,
    WorkerTailoredResumeView,
)

router = DefaultRouter()
router.register(r"applications", JobApplicationViewSet, basename="application")
router.register(r"leads", JobLeadViewSet, basename="lead")
router.register(r"agent-tasks", AgentTaskViewSet, basename="agenttask")

# The user-facing API (session-authenticated, scoped to the logged-in person).
urlpatterns = [
    path("stats/", StatsView.as_view(), name="stats"),
    path("resume/", ResumeView.as_view(), name="resume"),
    # Download your OWN resume PDF (login-gated). The only browser path to the
    # bytes — nginx no longer serves /media/ resumes unauthenticated.
    path("resume/pdf/", ResumePdfView.as_view(), name="resume-pdf"),
    path("", include(router.urls)),
]

# The host worker's API (machine caller). These are NOT session-authenticated:
#   - queue read + task update + profile write  → shared worker secret
#   - lead/application create                    → per-task token (scoped owner)
# Kept under /worker/ so it is obvious these are the machine endpoints.
urlpatterns += [
    path("worker/tasks/", WorkerTasksView.as_view(), name="worker-tasks"),
    path("worker/tasks/<int:pk>/", WorkerTaskUpdateView.as_view(), name="worker-task-update"),
    path("worker/tasks/<int:pk>/profile/", WorkerResumeProfileView.as_view(), name="worker-task-profile"),
    path("worker/tasks/<int:pk>/resume.pdf", WorkerResumePdfView.as_view(), name="worker-task-resume-pdf"),
    path("worker/leads/", WorkerLeadCreateView.as_view(), name="worker-lead-create"),
    path("worker/applications/", WorkerApplicationCreateView.as_view(), name="worker-application-create"),
    # The tailoring worker posts finished tailored-resume content here; the
    # backend builds the .docx and attaches it to the task-owner's lead.
    path("worker/tailored-resume/", WorkerTailoredResumeView.as_view(), name="worker-tailored-resume"),
]
