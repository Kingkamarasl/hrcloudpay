from django.core.management.base import BaseCommand
from payroll.models import PayrollRun
from regional.compliance import create_compliance_pack


class Command(BaseCommand):
    help = 'Prepare statutory compliance packs for approved or paid payroll runs.'

    def handle(self, *args, **options):
        count = 0
        for run in PayrollRun.objects.filter(status__in=['approved', 'paid']).select_related('company'):
            if create_compliance_pack(run):
                count += 1
        self.stdout.write(self.style.SUCCESS(f'Prepared/refreshed {count} compliance pack(s).'))
