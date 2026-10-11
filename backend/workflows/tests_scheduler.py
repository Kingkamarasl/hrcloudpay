"""The scheduled maintenance loop.

`run_hr_automations` and its six siblings were all implemented, all tested and
all unreachable in production: nothing invoked them except a person SSHing into
the server or pressing "Run now" in the browser. The product advertised
proactive HR alerts, so this module guards the wiring rather than the behaviour
- the individual commands keep their own tests.
"""

import pathlib
import re

from django.test import SimpleTestCase

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy' / 'run_scheduled.sh'
COMPOSE = ROOT / 'docker-compose.prod.yml'

# Commands that only run when a human asks. Auto-scheduling these would be
# actively wrong - they delete rows, write to disk, or seed reference data.
NEVER_SCHEDULED = [
    'debug_delete', 'delete_employee', 'createsuperuser', 'create_backup',
    'verify_backup', 'seed_country_rules', 'seed_filing_rules',
    'seed_feature_flags', 'revoke_api_tokens', 'seal_audit_backlog',
]


def _yaml():
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML ships with the image
        return None
    return yaml.safe_load(COMPOSE.read_text(encoding='utf-8'))


def _scheduled_commands():
    """Every command the script will actually run, in order."""
    return re.findall(r'^run_every\s+(\w+)\s+\d+\s*$', SCRIPT.read_text(encoding='utf-8'), re.M)


class SchedulerScriptTests(SimpleTestCase):
    def setUp(self):
        self.source = SCRIPT.read_text(encoding='utf-8')

    def test_script_exists_and_is_posix_shell(self):
        self.assertTrue(SCRIPT.exists(), 'deploy/run_scheduled.sh is missing')
        self.assertIn('#!/bin/sh', self.source)

    def test_one_failing_command_cannot_stop_the_loop(self):
        """A transient database error at 03:00 must not end all scheduling.

        `set -e` would abort the script on the first non-zero exit, leaving every
        later command unrun until someone noticed and restarted the stack. The
        loop would come back silently, with nothing in the logs to explain the
        gap.
        """
        self.assertNotIn('\nset -e', self.source)
        self.assertIn('set -u', self.source)

    def test_failure_is_not_recorded_as_success(self):
        """The stamp is only written when the command exits zero.

        Writing it unconditionally would turn one failed run into a silent
        24-hour gap, since the command would then look "not yet due".
        """
        # The stamp write has to live in the success branch, or failure retries.
        self.assertIn('FAILED - will retry', self.source)

        body = self.source.split('if $MANAGE', 1)[1].split('\n    fi', 1)[0]
        stamp = body.index('echo "$_now" > "$_stamp"')
        self.assertLess(
            body.index('then'), stamp,
            'the success stamp must be written inside the then branch',
        )
        self.assertGreater(
            body.index('else'), stamp,
            'writing the stamp after the else branch records failures as success',
        )

    def test_automation_commands_are_scheduled(self):
        """The commands that make proactive HR alerts fire at all."""
        scheduled = _scheduled_commands()
        for command in ['run_hr_automations', 'accrue_leave', 'check_document_expiry',
                        'process_contract_expiries', 'generate_statutory_filings',
                        'run_due_integrations']:
            self.assertIn(command, scheduled, f'{command} is never scheduled')

    def test_every_scheduled_command_exists(self):
        """Catches a typo, which would otherwise fail once an hour forever.

        The loop logs "FAILED" and moves on, so a misspelled command name is
        indistinguishable from a working deployment in the container logs.
        """
        for command in _scheduled_commands():
            found = list((ROOT / 'backend').glob(f'*/management/commands/{command}.py'))
            self.assertTrue(
                found,
                f'run_scheduled.sh runs "{command}" but no such management command exists',
            )

    def test_destructive_commands_are_never_scheduled(self):
        scheduled = _scheduled_commands()
        for command in NEVER_SCHEDULED:
            self.assertNotIn(command, scheduled, f'{command} must not run unattended')

    def test_the_loop_actually_repeats(self):
        """The script runs one pass; the repeat is the container command's job."""
        self.assertIn('sleep "$INTERVAL"', self.source)


class SchedulerComposeTests(SimpleTestCase):
    def setUp(self):
        self.data = _yaml()
        if self.data is None:
            self.skipTest('PyYAML is unavailable')

    def test_scheduler_service_exists(self):
        self.assertIn('scheduler', self.data['services'])

    def test_scheduler_shares_the_backend_environment(self):
        """Same image, same settings.

        `run_hr_automations` writes HRNotification rows and audit entries using
        the configured database and mail sender. A scheduler with a different
        DATABASE_URL or EMAIL_BACKEND would post notifications the web process
        cannot account for.
        """
        backend = self.data['services']['backend']['environment']
        scheduler = self.data['services']['scheduler']['environment']
        for key in ['DATABASE_URL', 'SECRET_KEY', 'REDIS_URL', 'EMAIL_BACKEND']:
            self.assertEqual(backend.get(key), scheduler.get(key), f'{key} differs')

    def test_scheduler_is_not_reachable_from_the_internet(self):
        """Only Caddy may publish ports."""
        self.assertNotIn('ports', self.data['services']['scheduler'])

    def test_scheduler_state_survives_a_restart(self):
        """Otherwise every restart re-runs the daily batch at once."""
        mounts = ' '.join(self.data['services']['scheduler']['volumes'])
        self.assertIn('scheduler_state', mounts)
        self.assertIn('scheduler_state', self.data['volumes'])

    def test_scheduler_runs_the_script(self):
        command = ' '.join(self.data['services']['scheduler']['command'])
        self.assertIn('run_scheduled.sh', command)
        self.assertIn('while true', command)