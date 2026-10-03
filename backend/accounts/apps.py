from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Seed catalog flags once DB is available (ignore errors during migrate)
        try:
            from django.db import connection
            if connection.introspection.table_names():
                from .features import ensure_default_flags
                ensure_default_flags()
        except Exception:
            pass
