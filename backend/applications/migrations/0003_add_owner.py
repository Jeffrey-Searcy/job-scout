"""
Add per-user ownership to JobApplication, JobLead, and AgentTask.

This is the multi-user cutover. Before it, all rows were global (single-user
app). It runs in a safe, non-destructive order:

  1. Add ``owner`` as NULLABLE on all three models (existing rows get NULL).
  2. Backfill: assign every pre-existing row to one owner (see assign_owner).
  3. Make ``owner`` NON-NULL now that no row is NULL.
  4. Replace JobLead's (company, title, url) unique key with one that includes
     owner, so two users can independently hold the same posting.

Backfill policy (no silent guessing): pre-existing rows belong to the original
single user. We pick that user as, in order, the first superuser, else the
first user by id. If there are rows to assign but NO users exist at all, we
raise — rather than invent an owner or drop the data — so the operator creates
an account first and re-runs. Fresh databases (no rows) skip cleanly.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_owner(apps, schema_editor):
    """Assign every ownerless existing row to the original single user.

    Raises RuntimeError if data exists but no user account does — we never
    fabricate an owner or silently discard rows.
    """
    User = apps.get_model(settings.AUTH_USER_MODEL.split(".")[0], settings.AUTH_USER_MODEL.split(".")[1])
    JobApplication = apps.get_model("applications", "JobApplication")
    JobLead = apps.get_model("applications", "JobLead")
    AgentTask = apps.get_model("applications", "AgentTask")

    has_rows = (
        JobApplication.objects.exists()
        or JobLead.objects.exists()
        or AgentTask.objects.exists()
    )
    if not has_rows:
        return  # Fresh DB: nothing to backfill.

    # Prefer a superuser (the app owner); fall back to the earliest user.
    owner = User.objects.filter(is_superuser=True).order_by("id").first()
    if owner is None:
        owner = User.objects.order_by("id").first()
    if owner is None:
        raise RuntimeError(
            "Existing job data found but no user account exists to own it. "
            "Create an account first (e.g. `python manage.py createsuperuser` "
            "or sign up once via /api/auth/signup/), then re-run this migration."
        )

    JobApplication.objects.filter(owner__isnull=True).update(owner=owner)
    JobLead.objects.filter(owner__isnull=True).update(owner=owner)
    AgentTask.objects.filter(owner__isnull=True).update(owner=owner)


def unassign_owner(apps, schema_editor):
    """Reverse of the backfill: no-op.

    On reverse, the schema operations below revert owner to nullable and drop
    the column, so there is nothing to undo at the data level.
    """
    return


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0002_agenttask"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Add owner as NULLABLE everywhere so existing rows are allowed.
        migrations.AddField(
            model_name="jobapplication",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="applications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="joblead",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="leads",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="agenttask",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="agent_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 2. Backfill owners for pre-existing rows.
        migrations.RunPython(assign_owner, unassign_owner),
        # 3. Now that no row is NULL, make owner required.
        migrations.AlterField(
            model_name="jobapplication",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="applications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="joblead",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="leads",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="agenttask",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="agent_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 4. Swap the lead uniqueness to be per-owner.
        migrations.RemoveConstraint(
            model_name="joblead",
            name="uniq_lead",
        ),
        migrations.AddConstraint(
            model_name="joblead",
            constraint=models.UniqueConstraint(
                fields=["owner", "company", "title", "url"], name="uniq_lead"
            ),
        ),
    ]
