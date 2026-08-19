"""DRF serializers: translate model instances to/from JSON for the REST API."""
from django.utils import timezone
from rest_framework import serializers

from .models import JobApplication, JobLead, AgentTask, Status, LeadStatus


class JobApplicationSerializer(serializers.ModelSerializer):
    """Serializes a JobApplication, adding computed display fields for the UI."""

    salary_display = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = JobApplication
        fields = "__all__"

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
    """Serializes a JobLead (scout inbox item)."""

    class Meta:
        model = JobLead
        fields = "__all__"

    def validate(self, attrs):
        """Reject a lead for a posting already in the pipeline or inbox.

        The scout can otherwise re-surface a role the candidate has already
        applied to (or already has queued), because the model's own uniqueness
        only compares leads to other leads. We match on the apply URL, which is
        the stable identity of a posting. A URL tied only to a rejected/ghosted
        application is allowed through — re-surfacing a dead role is fine.
        Creates only; updates (self.instance set) skip the check.
        """
        if self.instance is not None:
            return attrs
        url = (attrs.get("url") or "").strip()
        if not url:
            return attrs  # No URL to match on; nothing to dedupe against.

        # Already an active application for this posting?
        clashing_app = (
            JobApplication.objects.filter(link=url)
            .exclude(status__in=[Status.REJECTED, Status.GHOSTED])
            .first()
        )
        if clashing_app is not None:
            raise serializers.ValidationError(
                {"url": f"Already in your pipeline as an application "
                        f"(#{clashing_app.id}, status '{clashing_app.status}'). Not re-added."}
            )

        # Already a live lead for this posting (ignore ones you dismissed)?
        clashing_lead = (
            JobLead.objects.filter(url=url)
            .exclude(status=LeadStatus.DISMISSED)
            .first()
        )
        if clashing_lead is not None:
            raise serializers.ValidationError(
                {"url": f"Already in your scout inbox (lead #{clashing_lead.id}). Not re-added."}
            )
        return attrs


class AgentTaskSerializer(serializers.ModelSerializer):
    """Serializes an AgentTask (AI work request + its status/result)."""

    class Meta:
        model = AgentTask
        fields = "__all__"
