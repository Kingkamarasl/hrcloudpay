import hashlib, json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
class Command(BaseCommand):
    def add_arguments(self,p): p.add_argument('backup')
    def handle(self,*args,**opts):
        path=Path(opts['backup']); manifest=Path(str(path)+'.json')
        if not path.exists() or not manifest.exists(): raise CommandError('Backup or manifest not found.')
        expected=json.loads(manifest.read_text())['sha256']; actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual!=expected: raise CommandError('Backup integrity check failed.')
        self.stdout.write(self.style.SUCCESS('Backup integrity verified.'))
