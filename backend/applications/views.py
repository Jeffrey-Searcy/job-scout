"""
REST API views (API-first).

Endpoints:
  - /api/applications/         CRUD for pipeline applications
  - /api/leads/                CRUD for scout leads (+ /leads/{id}/promote/)
  - /api/agent-tasks/          create/list AI work requests (+ ?status= filter)
  - /api/stats/                pipeline summary for the dashboard
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import JobApplication, JobLead, AgentTask
from .serializers import JobApplicationSerializer, JobLeadSerializer, AgentTaskSerializer
from .services import pipeline_stats


class JobApplicationViewSet(viewsets.ModelViewSet):
    """Full CRUD for pipeline applications, ordered newest-applied first."""

    queryset = JobApplication.objects.all()
    serializer_class = JobApplicationSerializer


class JobLeadViewSet(viewsets.ModelViewSet):
    """CRUD for scout leads, plus a 'promote' action to turn one into an application."""

    queryset = JobLead.objects.all()
    serializer_class = JobLeadSerializer

    @action(detail=True, methods=["post"])
    def promote(self, request, pk=None):
        """POST /api/leads/{id}/promote/ — create an application from this lead."""
        lead = self.get_object()
        application = lead.promote_to_application()
        return Response(JobApplicationSerializer(application).data, status=status.HTTP_201_CREATED)


class AgentTaskViewSet(viewsets.ModelViewSet):
    """Create/list/update AI work requests. Supports ?status=pending for the worker."""

    serializer_class = AgentTaskSerializer

    def get_queryset(self):
        """Return all tasks, optionally filtered by ?status= (used by the worker)."""
        qs = AgentTask.objects.all()
        state = self.request.query_params.get("status")
        return qs.filter(status=state) if state else qs


class StatsView(APIView):
    """GET /api/stats/ — pipeline metrics for the dashboard tiles and funnel."""

    def get(self, request):
        """Return the computed pipeline stats as JSON."""
        return Response(pipeline_stats())
