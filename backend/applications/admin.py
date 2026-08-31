"""Django admin registration so the data is browsable at /admin/ too."""
from django.contrib import admin

from .models import JobApplication, JobLead, AgentTask, Resume, TaskToken


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    """Admin list view tuned for quickly scanning the pipeline."""

    list_display = ("company", "role", "owner", "status", "work_mode", "is_local", "fit", "applied_date")
    list_filter = ("owner", "status", "work_mode", "fit", "is_local")
    search_fields = ("company", "role", "notes")


@admin.register(JobLead)
class JobLeadAdmin(admin.ModelAdmin):
    """Admin list view for the scout leads inbox."""

    list_display = ("company", "title", "owner", "status", "work_mode", "is_local", "discovered_date")
    list_filter = ("owner", "status", "work_mode", "is_local")
    search_fields = ("company", "title", "summary")


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    """Admin view for AI work requests and their outcomes."""

    list_display = ("id", "kind", "owner", "status", "created_at")
    list_filter = ("owner", "kind", "status")


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    """Admin view for uploaded resumes and their distilled profiles."""

    list_display = ("owner", "profile_ready", "updated_at")
    list_filter = ("owner",)


@admin.register(TaskToken)
class TaskTokenAdmin(admin.ModelAdmin):
    """Admin view for per-task worker write-credentials.

    The secret token string is intentionally excluded from list_display so it is
    not casually shown; only its task, owner, expiry, and used flag appear.
    """

    list_display = ("task", "owner", "expires_at", "used", "created_at")
    list_filter = ("owner", "used")
