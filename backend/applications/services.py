"""
Business logic kept out of the views (thin views, fat services).

Centralizing the pipeline math here means the API, the admin, and any future
caller compute stats the same way.
"""
from django.db.models import Count

from .models import JobApplication, JobLead, Status, LeadStatus


def pipeline_stats(user):
    """Return pipeline metrics for ONE user's dashboard (tiles + funnel).

    Every count is scoped to ``user`` so each person sees only their own
    numbers. Callers pass request.user; there is no global, all-users variant
    by design.

    Shape:
        {
          "total": int,
          "active": int,            # advanced past 'Applied'
          "local": int,
          "strong": int,
          "by_status": {status: count, ...},
          "new_leads": int,
        }
    """
    apps = JobApplication.objects.filter(owner=user)
    by_status = {row["status"]: row["count"] for row in apps.values("status").annotate(count=Count("id"))}

    # Cumulative funnel: how many reached each stage or beyond.
    advanced = (Status.PHONE_SCREEN, Status.INTERVIEW, Status.TAKE_HOME, Status.ONSITE, Status.OFFER)
    reached_phone = sum(by_status.get(s, 0) for s in advanced)
    reached_interview = sum(by_status.get(s, 0) for s in (Status.INTERVIEW, Status.TAKE_HOME, Status.ONSITE, Status.OFFER))
    reached_offer = by_status.get(Status.OFFER, 0)

    return {
        "total": apps.count(),
        "active": sum(1 for a in apps if a.is_active),
        "local": apps.filter(is_local=True).count(),
        "strong": apps.filter(fit="strong").count(),
        "by_status": by_status,
        "funnel": {
            "applied": apps.count(),
            "phone_screen": reached_phone,
            "interview": reached_interview,
            "offer": reached_offer,
        },
        "new_leads": JobLead.objects.filter(owner=user, status=LeadStatus.NEW).count(),
    }
