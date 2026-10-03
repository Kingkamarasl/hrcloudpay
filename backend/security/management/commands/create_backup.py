import hashlib, json, os, shutil, subprocess
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


def _sha256_file(path, chunk=1024 * 1024):
    """Digest a file without loading it into memory.

    The previous implementation used ``path.read_bytes()``. A development
    database is a couple of megabytes so that was free, but this command exists
    to be run against production, where a dump is gigabytes - reading one
    wholesale into a Python process is how a backup job takes down the very
    instance it was meant to protect.
    """
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(chunk), b''):
            digest.update(block)
    return digest.hexdigest()


def _media_backup_caveat(command, storage_backend):
    """Say plainly what this backup does not contain.

    A database backup records the *name* of every uploaded file, not the file.
    Restoring into an environment whose object storage is empty, or whose local
    MEDIA_ROOT was replaced by a fresh container, yields a working application
    full of rows that point at files which are not there: payslip attachments
    missing, contract scans gone, knowledge-base sources unavailable. That is a
    silent and confusing failure, so it is named at backup time rather than
    discovered during an incident.
    """
    if 'S3' in storage_backend:
        command.stdout.write(
            command.style.WARNING(
                'NOTE: this backup contains the DATABASE only. Uploaded files '
                'live in the S3 bucket and are NOT in this dump. The bucket must '
                'have versioning and/or replication enabled and its own backup '
                'policy - verify the objects referenced by these rows exist '
                'before relying on this dump.'
            )
        )
    else:
        media_root = Path(getattr(settings, 'MEDIA_ROOT', ''))
        count = 0
        if media_root.is_dir():
            count = sum(1 for p in media_root.rglob('*') if p.is_file())
        command.stdout.write(
            command.style.WARNING(
                f'NOTE: this backup contains the DATABASE only. MEDIA_ROOT '
                f'({media_root}) holds {count} file(s) which are NOT in this '
                f'dump. On a container platform that directory does not survive '
                f'a deploy, so uploaded employee documents must be moved to '
                f'object storage and backed up separately.'
            )
        )


class Command(BaseCommand):
    help='Create an integrity-checked application database backup.'

    def add_arguments(self, p):
        p.add_argument('--output', default='backups')

    def handle(self, *args, **opts):
        out = Path(opts['output']); out.mkdir(parents=True, exist_ok=True)
        stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
        db = settings.DATABASES['default']; engine = db['ENGINE']

        if engine.endswith('sqlite3'):
            src = Path(db['NAME']); dest = out / f'hrcloudpay-{stamp}.sqlite3'
            shutil.copy2(src, dest)
        elif 'postgresql' in engine:
            dest = out / f'hrcloudpay-{stamp}.dump'
            # The host, port and user must be passed explicitly. `pg_dump NAME`
            # alone connects over the local unix socket as the OS user, so on a
            # managed instance - which is where this is meant to run - it either
            # fails outright or, worse, succeeds against a different database.
            cmd = ['pg_dump', '-Fc', '-f', str(dest), '-h', str(db.get('HOST') or 'localhost'),
                   '-p', str(db.get('PORT') or 5432), '-U', str(db.get('USER') or ''),
                   str(db['NAME'])]
            child_env = dict(os.environ)
            # The password goes in the child's environment, never on the
            # command line, where it would be visible to every process on the
            # host via `ps`.
            if db.get('PASSWORD'):
                child_env['PGPASSWORD'] = str(db['PASSWORD'])
            if db.get('OPTIONS', {}).get('sslmode'):
                child_env['PGSSLMODE'] = str(db['OPTIONS']['sslmode'])
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, env=child_env)
            except FileNotFoundError:
                raise CommandError('pg_dump is required for PostgreSQL backups.')
            except subprocess.CalledProcessError as exc:
                # Surface the real reason. The previous version swallowed it, so
                # a backup that failed on a permissions or TLS problem still
                # looked like a routine run from the exit status alone.
                raise CommandError(f'pg_dump failed: {exc.stderr.strip() or exc}')
        else:
            raise CommandError(f'Unsupported database engine: {engine}')

        if not dest.exists() or dest.stat().st_size == 0:
            raise CommandError(f'Backup file is missing or empty: {dest}')

        digest = _sha256_file(dest)
        manifest = dest.with_suffix(dest.suffix + '.json')
        manifest.write_text(json.dumps({
            'file': str(dest),
            'sha256': digest,
            'created_at': stamp,
            'bytes': dest.stat().st_size,
            'contains_media': False,
        }, indent=2))
        self.stdout.write(self.style.SUCCESS(f'Backup created: {dest}'))
        self.stdout.write(f'  sha256 {digest}')
        self.stdout.write(f'  {dest.stat().st_size} bytes')
        _media_backup_caveat(self, settings.STORAGES['default']['BACKEND'])
