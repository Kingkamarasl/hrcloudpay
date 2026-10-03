"""
Monthly leave accrual for all companies.

Run via cron, e.g. on the 1st of each month:
  python manage.py accrue_leave
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from accounts.models import Company
from employees.models import Employee
from leave.models import LeaveAccrualPolicy, LeaveBalance


class Command(BaseCommand):
    help = 'Accrue one month of leave for every active employee per company policies.'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=int, default=None)

    def handle(self, *args, **options):
        companies = Company.objects.filter(is_active=True)
        if options.get('company_id'):
            companies = companies.filter(id=options['company_id'])
        total = 0
        for company in companies:
            policies = list(LeaveAccrualPolicy.objects.filter(company=company, accrue_monthly=True))
            if not policies:
                continue
            for emp in Employee.objects.filter(company=company, employment_status='active'):
                for pol in policies:
                    bal, _ = LeaveBalance.objects.get_or_create(
                        employee=emp, leave_type=pol.leave_type, defaults={'balance_days': 0},
                    )
                    bal.balance_days = bal.balance_days + pol.monthly_accrual
                    bal.save(update_fields=['balance_days', 'updated_at'])
                    total += 1
            self.stdout.write(f'{company.name}: accrued for {len(policies)} policies')
        self.stdout.write(self.style.SUCCESS(f'Updated {total} balance rows'))
