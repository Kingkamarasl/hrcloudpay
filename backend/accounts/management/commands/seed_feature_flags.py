from django.core.management.base import BaseCommand
from accounts.features import ensure_default_flags


class Command(BaseCommand):
    help = 'Create default platform feature flags (does not override enabled state of existing keys).'

    def handle(self, *args, **options):
        created = ensure_default_flags()
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created flags: {", ".join(created)}'))
        else:
            self.stdout.write('All default feature flags already exist.')
