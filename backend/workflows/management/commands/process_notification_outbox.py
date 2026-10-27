from django.core.management.base import BaseCommand
from workflows.services import process_notification_outbox


class Command(BaseCommand):
    help = 'Deliver pending notification emails and retry transient failures.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        result = process_notification_outbox(limit=max(1, min(options['limit'], 500)))
        self.stdout.write(self.style.SUCCESS(str(result)))
