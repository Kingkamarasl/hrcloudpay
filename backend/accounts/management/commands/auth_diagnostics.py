from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Check local HRCloudPay authentication prerequisites without exposing secrets."

    def handle(self, *args, **options):
        User = get_user_model()
        self.stdout.write(f"DEBUG={settings.DEBUG}")
        self.stdout.write(f"Database={connection.vendor}")
        tables = set(connection.introspection.table_names())
        required = [
            User._meta.db_table,
            'security_securitysession',
            'security_securityevent',
        ]
        for table in required:
            self.stdout.write(f"TABLE {table}: {'OK' if table in tables else 'MISSING'}")
        self.stdout.write(f"USERS={User.objects.count() if User._meta.db_table in tables else 'unavailable'}")
        self.stdout.write("Authentication diagnostics complete.")
