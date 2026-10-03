"""Recompute the audit chain and report tampering.

Run this on a schedule (cron / Task Scheduler) alongside the existing backup
verification. The Security Center health check only samples the head of the
chain because a full walk is O(rows); this command is the exhaustive one.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from accounts.audit_chain import verify_chain


class Command(BaseCommand):
    help = 'Verify the tamper-evident audit chain by recomputing every integrity hash.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Only check the first N records (default: the whole chain).',
        )
        parser.add_argument(
            '--max-errors', type=int, default=100,
            help='Stop reporting after this many problems (default: 100).',
        )
        parser.add_argument(
            '--json', action='store_true', help='Emit machine-readable JSON.',
        )
        parser.add_argument(
            '--quiet', action='store_true',
            help='Exit non-zero on failure without printing details.',
        )

    def handle(self, *args, **opts):
        result = verify_chain(
            limit=opts['limit'],
            max_errors=opts['max_errors'],
        )

        if opts['json']:
            self.stdout.write(json.dumps(result, default=str, indent=2))
        elif result['ok']:
            scope = f'first {result["checked"]} record(s)' if result['truncated'] else f'{result["checked"]} record(s)'
            self.stdout.write(self.style.SUCCESS(f'Audit chain verified across {scope}.'))
        elif opts['quiet']:
            pass
        else:
            self.stderr.write(self.style.ERROR(f'Audit chain verification FAILED ({len(result["problems"])} problem(s)):'))
            for problem in result['problems']:
                self.stderr.write(f'  [{problem["kind"]}] sequence={problem["sequence"]} {problem["detail"]}')

        if not result['ok']:
            raise CommandError(
                'Audit chain verification failed. The audit trail cannot be trusted '
                'until this is investigated.'
            )
