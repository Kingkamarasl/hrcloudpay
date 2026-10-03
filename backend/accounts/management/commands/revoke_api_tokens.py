"""Revoke long-lived DRF API tokens.

`/auth/login/` and `/auth/register/` used to return a DRF `Token` that was
created with `get_or_create` and never rotated. That made it a permanent
bearer credential: no expiry, no rotation, and `POST /auth/logout/` deleting it
could not invalidate a stolen copy held elsewhere. The SPA never used it - it
authenticates with the HttpOnly `hrcloudpay_session` cookie - so those responses
no longer issue one.

Tokens issued before that change are still valid until revoked here, which
matters most on a shared machine or after a suspected leak. Existing clients
keep working: nothing about `TokenAuthentication` was removed.
"""

from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = 'Revoke DRF API tokens. Use --user to target one account.'

    def add_arguments(self, parser):
        parser.add_argument('--user', help='Revoke only this username.')
        parser.add_argument(
            '--dry-run', action='store_true', help='Report what would be revoked.',
        )

    def handle(self, *args, **opts):
        tokens = Token.objects.select_related('user')
        if opts['user']:
            tokens = tokens.filter(user__username=opts['user'])
        count = tokens.count()

        if opts['dry_run']:
            self.stdout.write(f'Would revoke {count} API token(s).')
            for token in tokens[:50]:
                self.stdout.write(f'  {token.user.username} created {token.created}')
            return

        deleted, _ = tokens.delete()
        self.stdout.write(self.style.SUCCESS(f'Revoked {deleted} API token(s).'))
