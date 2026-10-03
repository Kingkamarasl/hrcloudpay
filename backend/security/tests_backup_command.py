"""The backup command has to be trustworthy, because it is the last resort.

Two defects made this command actively misleading rather than merely incomplete:

* ``pg_dump`` was invoked as ``pg_dump NAME``, which connects over the local
  unix socket as the operating-system user. The database it was pointed at is
  a managed instance reached over TCP with a password, so on a real deployment
  the dump either failed or - worse - succeeded against a different database
  than the application uses. The command exited without saying which.
* The digest was computed with ``path.read_bytes()``, pulling the whole dump
  into memory. Fine at 1.5 MB, an out-of-memory kill at production size, on the
  instance the backup was meant to protect.

And one thing it never said: it backs up the database only. Restoring it into
an environment whose object storage is empty gives a working application full
of rows pointing at files that are not there. The command now states that.
"""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class SqliteBackupTests(SimpleTestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix='hrcloudpay-backup-')

    def test_it_writes_a_dump_and_a_verifiable_manifest(self):
        source = Path(tempfile.mkdtemp()) / 'db.sqlite3'
        source.write_bytes(b'SQLite format 3\x00' + b'x' * 4096)

        with override_settings(
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(source)}},
            MEDIA_ROOT=str(Path(tempfile.mkdtemp())),
        ):
            call_command('create_backup', f'--output={self.out}', verbosity=0)

        dumps = list(Path(self.out).glob('*.sqlite3'))
        self.assertEqual(len(dumps), 1, 'no dump was produced')
        manifest = json.loads(Path(str(dumps[0]) + '.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['sha256']), 64)
        self.assertEqual(manifest['bytes'], dumps[0].stat().st_size)
        # The whole point of the manifest is that verify_backup can check it.
        self.assertFalse(manifest['contains_media'])

    def test_verify_backup_accepts_a_freshly_made_backup(self):
        source = Path(tempfile.mkdtemp()) / 'db.sqlite3'
        source.write_bytes(b'SQLite format 3\x00' + b'y' * 2048)
        with override_settings(
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(source)}},
            MEDIA_ROOT=str(Path(tempfile.mkdtemp())),
        ):
            call_command('create_backup', f'--output={self.out}', verbosity=0)
            call_command('verify_backup', str(next(Path(self.out).glob('*.sqlite3'))), verbosity=0)


class PostgresBackupTests(SimpleTestCase):
    """The arguments matter more than anything else here."""

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix='hrcloudpay-backup-pg-')

    def run_backup(self):
        with override_settings(DATABASES={'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'hrcloudpay', 'USER': 'hruser', 'PASSWORD': 'p@ss word',
            'HOST': 'db.internal', 'PORT': 6432,
            'OPTIONS': {'sslmode': 'require'},
        }}, MEDIA_ROOT=str(Path(tempfile.mkdtemp()))):
            call_command('create_backup', f'--output={self.out}', verbosity=0)

    def test_pg_dump_is_told_where_the_database_actually_is(self):
        """Reverting to `pg_dump NAME` makes this test fail."""
        with mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(returncode=0, stderr='')
            # pg_dump is mocked, so no file appears; assert on the arguments.
            with self.assertRaises(CommandError):
                self.run_backup()

        argv = run.call_args[0][0]
        self.assertIn('-h', argv)
        self.assertIn('db.internal', argv)
        self.assertIn('-p', argv)
        self.assertIn('6432', argv)
        self.assertIn('-U', argv)
        self.assertIn('hruser', argv)
        self.assertIn('hrcloudpay', argv)

    def test_the_password_is_passed_out_of_the_command_line(self):
        """argv is world-readable through `ps`; the env is not."""
        with mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(returncode=0, stderr='')
            with self.assertRaises(CommandError):
                self.run_backup()

        argv = run.call_args[0][0]
        self.assertNotIn('p@ss word', argv)
        self.assertEqual(run.call_args[1]['env']['PGPASSWORD'], 'p@ss word')

    def test_tls_mode_is_carried_over_to_pg_dump(self):
        with mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(returncode=0, stderr='')
            with self.assertRaises(CommandError):
                self.run_backup()
        self.assertEqual(run.call_args[1]['env']['PGSSLMODE'], 'require')

    def test_a_failing_pg_dump_is_reported_rather_than_swallowed(self):
        failure = subprocess.CalledProcessError(1, 'pg_dump', stderr='permission denied')
        with mock.patch('subprocess.run', side_effect=failure):
            with self.assertRaises(CommandError) as caught:
                self.run_backup()
        self.assertIn('permission denied', str(caught.exception))

    def test_an_empty_dump_is_treated_as_a_failure(self):
        """A zero-byte dump plus a matching digest looks like success."""
        with mock.patch('subprocess.run') as run:
            def fake(cmd, **kwargs):
                Path(cmd[cmd.index('-f') + 1]).write_bytes(b'')
                return mock.Mock(returncode=0, stderr='')
            run.side_effect = fake
            with self.assertRaises(CommandError) as caught:
                self.run_backup()
        self.assertIn('missing or empty', str(caught.exception))


class BackupMediaCaveatTests(SimpleTestCase):
    """A restore needs the files as much as the rows that name them."""

    def test_it_says_media_is_not_included(self):
        out = tempfile.mkdtemp(prefix='hrcloudpay-backup-note-')
        source = Path(tempfile.mkdtemp()) / 'db.sqlite3'
        source.write_bytes(b'SQLite format 3\x00')
        with override_settings(
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(source)}},
            MEDIA_ROOT=str(Path(tempfile.mkdtemp())),
        ):
            call_command('create_backup', f'--output={out}', verbosity=1)


class DigestTests(SimpleTestCase):
    def test_streaming_digest_matches_a_known_value(self):
        from security.management.commands.create_backup import _sha256_file
        import hashlib
        path = Path(tempfile.mkdtemp()) / 'blob'
        payload = b'payroll' * 500_000  # larger than one 1MB chunk
        path.write_bytes(payload)
        self.assertEqual(_sha256_file(path), hashlib.sha256(payload).hexdigest())
