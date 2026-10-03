from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from employees.models import Contract, Employee, EmploymentEvent
from employees.services import ContractService
from accounts.audit import audit
import logging

logger = logging.getLogger('hrcloudpay')

class Command(BaseCommand):
    help = 'Automatically processes contracts that have reached their end date.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        self.stdout.write(f"Scanning for expired contracts as of {today}...")

        # Find active employees with contracts that ended today or earlier
        expired_contracts = Contract.objects.filter(
            end_date__lte=today,
            employee__employment_status='active'
        ).select_related('employee', 'employee__company')

        count = expired_contracts.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No expired contracts found."))
            return

        self.stdout.write(f"Found {count} expired contracts. Processing...")

        processed_count = 0
        for contract in expired_contracts:
            employee = contract.employee
            company = employee.company
            
            try:
                with transaction.atomic():
                    # 1. Update Employee Status
                    old_status = employee.employment_status
                    employee.employment_status = 'terminated'
                    employee.save(update_fields=['employment_status', 'updated_at'])

                    # 2. Record Employment Event
                    EmploymentEvent.objects.create(
                        employee=employee,
                        event_type='terminated',
                        effective_date=contract.end_date,
                        title='Automatic Contract Expiry',
                        description=f'Employee status updated to terminated automatically due to contract end date ({contract.end_date}).',
                        created_by=None # System action
                    )

                    # 3. Audit the change
                    audit(
                        actor=None, # System
                        action='contract_expiry',
                        message=f'Automatic expiry: {employee.full_name} contract ended on {contract.end_date}',
                        company=company,
                        target_type='employee',
                        target_id=employee.id,
                        metadata={'end_date': str(contract.end_date), 'previous_status': old_status}
                    )
                    
                    processed_count += 1
                    self.stdout.write(f"Processed expiry for {employee.full_name}")

            except Exception as e:
                logger.error(f"Failed to process expiry for employee {employee.id}: {e}")
                self.stdout.write(self.style.ERROR(f"Error processing {employee.full_name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {processed_count}/{count} contract expiries."))
