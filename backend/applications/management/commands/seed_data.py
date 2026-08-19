"""
Optional sample-data seeder for demos and first-run screenshots.

This is intentionally GENERIC placeholder data so the public repo contains no
personal information. It only runs when you ask for it (e.g. SEED_SAMPLE=1 in the
container, or `python manage.py seed_data` locally). A fresh install otherwise
starts empty — add your own roles via the UI, the scout, or the MCP tools.
"""
from datetime import date

from django.core.management.base import BaseCommand

from applications.models import JobApplication

# Clearly-fictional examples so nobody's real search leaks into version control.
SEED = [
    dict(company="Acme Corp", role="Software Engineer II", source="Company site",
         link="https://example.com/acme/jobs/se2", status="phone_screen", work_mode="hybrid",
         location="Your City, ST", is_local=True, salary_min=110000, salary_max=140000,
         fit="strong", angle="Sample local role", notes="Sample data — replace with your own.",
         applied_date=date(2026, 1, 6), followup_date=date(2026, 1, 13)),
    dict(company="Globex", role="Full Stack Engineer", source="Greenhouse",
         link="https://example.com/globex/jobs/fse", status="applied", work_mode="remote",
         location="Remote · US", is_local=False, salary_min=130000, salary_max=170000,
         fit="good", angle="Sample remote role", notes="Sample data.",
         applied_date=date(2026, 1, 6), followup_date=date(2026, 1, 13)),
    dict(company="Initech", role="DevOps Engineer", source="Lever",
         link="https://example.com/initech/jobs/devops", status="applied", work_mode="onsite",
         location="Your City, ST", is_local=True, fit="stretch", angle="Sample stretch role",
         notes="Sample data.", applied_date=date(2026, 1, 5), followup_date=date(2026, 1, 12)),
]


class Command(BaseCommand):
    """`python manage.py seed_data` — load generic sample applications (idempotent)."""

    help = "Load generic SAMPLE applications for demos. Not real data."

    def handle(self, *args, **options):
        """Upsert the sample rows keyed on (company, role)."""
        created = 0
        for row in SEED:
            _, was_created = JobApplication.objects.update_or_create(
                company=row["company"], role=row["role"], defaults=row,
            )
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Sample seed done ({created} created)."))
