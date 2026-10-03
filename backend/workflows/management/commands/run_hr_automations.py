from django.core.management.base import BaseCommand
from workflows.services import run_due_automations
class Command(BaseCommand):
    help='Generate HR notifications and workflow tasks for due employee events.'
    def handle(self,*args,**kwargs): self.stdout.write(str(run_due_automations()))
