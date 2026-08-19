"""URL routing for the applications API (DRF router + the stats endpoint)."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import JobApplicationViewSet, JobLeadViewSet, AgentTaskViewSet, StatsView

router = DefaultRouter()
router.register(r"applications", JobApplicationViewSet, basename="application")
router.register(r"leads", JobLeadViewSet, basename="lead")
router.register(r"agent-tasks", AgentTaskViewSet, basename="agenttask")

urlpatterns = [
    path("stats/", StatsView.as_view(), name="stats"),
    path("", include(router.urls)),
]
