from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from employees.models import EmployeeDocument
import logging

logger = logging.getLogger('hrcloudpay')

class Command(BaseCommand):
    help = 'Scans for employee documents that are expiring soon and alerts HR.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', 
            type=int, 
            default=30, 
            help='Window of days to check for expiry (default: 30)'
        )

    def handle(self, *args, **options):
        days = options['days']
        today = timezone.localdate()
        expiry_limit = today + timedelta(days=days)
        
        self.stdout.write(f"Scanning for documents expiring between {today} and {expiry_limit}...")

        # Find documents that expire between today and the limit, and are not yet expired
        expiring_docs = EmployeeDocument.objects.filter(
            expiry_date__gte=today,
            expiry_date__lte=expiry_limit
        ).select_related('employee')

        count = expiring_docs.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No documents expiring soon."))
            return

        self.stdout.write(f"Found {count} documents expiring soon:\n")
        
        for doc in expiring_docs:
            msg = (
                f"ALERT: Document '{doc.title}' ({doc.get_document_type_display()}) "
                f"for {doc.employee.full_name} expires on {doc.expiry_date}."
            )
            self.stdout.write(self.style.WARNING(msg))
            # In a real system, we would trigger an Email/Push notification here.
            logger.warning(msg)

        self.stdout.write(self.style.SUCCESS(f"\nScan complete. {count} alerts generated."))
