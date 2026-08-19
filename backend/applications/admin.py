"""Django admin registration so the data is browsable at /admin/ too."""
from django.contrib import admin

from .models import JobApplication, JobLead, AgentTask


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    """Admin list view tuned for quickly scanning the pipeline."""

    list_display = ("company", "role", "status", "work_mode", "is_local", "fit", "applied_date")
    list_filter = ("status", "work_mode", "fit", "is_local")
    search_fields = ("company", "role", "notes")


@admin.register(JobLead)
class JobLeadAdmin(admin.ModelAdmin):
    """Admin list view for the scout leads inbox."""

    list_display = ("company", "title", "status", "work_mode", "is_local", "discovered_date")
    list_filter = ("status", "work_mode", "is_local")
    search_fields = ("company", "title", "summary")


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    """Admin view for AI work requests and their outcomes."""

    list_display = ("id", "kind", "status", "created_at")
    list_filter = ("kind", "status")
