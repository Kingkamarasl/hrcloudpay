"""One-time: enter audit rows written before the chain writer existed into the chain.

Why this is a command and not a migration
-----------------------------------------
``0005_tamper_evident_audit`` created the chain schema, seeded the head row, and
backfilled the rows that existed at that moment. ``AuditLog.save()`` then started
sealing new records. Any database that ran in between the two has rows with
``chain_sequence IS NULL``, and ``verify_audit_chain`` correctly refuses to
certify them - it has no digest to re-derive and no link to check.

This command is the continuation of that migration's backfill, using the same
ordering and the same digest. A new data migration would be the wrong tool twice
over: it would run implicitly on deploy, and it would present historical rows as
though they had always been sealed. They were not.

What it guarantees afterwards: every row belongs to one unbroken chain, and any
*future* modification to any of them is detected.

What it does not: that pre-sealing rows were untampered when written. They were
written when there was no mechanism that could have detected it either way.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.audit_chain import GENESIS_HASH
from accounts.platform_models import AuditChainState, AuditLog


class Command(BaseCommand):
    help = (
        'Seal pre-existing audit rows into the chain. Run once on a database '
        'that has rows with no chain_sequence. See the module docstring for '
        'what this does and does not guarantee.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be sealed without writing anything.',
        )

    def handle(self, *args, **options):
        backlog = AuditLog.objects.filter(chain_sequence__isnull=True).order_by(
            'created_at', 'id',
        )
        total = backlog.count()

        if not total:
            self.stdout.write(self.style.SUCCESS(
                'No unchained audit rows; nothing to do.'))
            return

        state = AuditChainState.objects.filter(key='global').first()
        if state is None:
            self.stdout.write(self.style.WARNING(
                'No chain head exists yet; this will start the chain at 1.'))
        else:
            self.stdout.write(
                f'Continuing from sequence {state.last_sequence}.')

        if options['dry_run']:
            self.stdout.write(
                f'Would seal {total} row(s) '
                f'({backlog.first().created_at:%Y-%m-%d %H:%M} onwards). '
                'Re-run without --dry-run to write.')
            return

        sealed = 0
        with transaction.atomic():
            for row in backlog.iterator(chunk_size=200):
                row._seal()
                sealed += 1

        self.stdout.write(self.style.SUCCESS(
            f'Sealed {sealed} pre-existing audit row(s).'))
        self.stdout.write(
            'These rows were written before the chain existed, so their contents '
            'were not verified at the time. From now on every modification to '
            'them is detected.'
        )