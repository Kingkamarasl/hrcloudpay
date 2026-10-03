from django.core.management.base import BaseCommand
from accounts.secrets import rotate_secret
from accounts.platform_models import PaymentProviderConfig
from ai.models import AIProviderConfig
from integrations.models import IntegrationProviderConfig
class Command(BaseCommand):
    help='Rotate encrypted provider secrets using the newest SECRET_ENCRYPTION_KEYS key.'
    def add_arguments(self,p): p.add_argument('--dry-run',action='store_true')
    def handle(self,*args,**opts):
        fields=[(PaymentProviderConfig,'encrypted_secret_key'),(PaymentProviderConfig,'webhook_secret'),(AIProviderConfig,'encrypted_api_key'),(IntegrationProviderConfig,'client_secret_encrypted')]
        total=0
        for model,field in fields:
            for obj in model.objects.exclude(**{f'{field}':''}):
                total+=1
                if not opts['dry_run']:
                    setattr(obj,field,rotate_secret(getattr(obj,field))); obj.save(update_fields=[field])
        self.stdout.write(self.style.SUCCESS(f'{"Would rotate" if opts["dry_run"] else "Rotated"} {total} encrypted values.'))
