from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from integrations.models import SyncSchedule
from integrations.sync_services import run_scheduled_sync

class Command(BaseCommand):
    help='Run due HRCloudPay integration schedules. Use cron/systemd/your task runner to invoke this command.'
    def handle(self,*args,**options):
        now=timezone.now(); count=0
        schedules=SyncSchedule.objects.select_related('connection').filter(enabled=True,next_run_at__lte=now,connection__status='connected')
        for schedule in schedules:
            try:
                result=run_scheduled_sync(schedule.connection)
                schedule.last_run_at=now; schedule.next_run_at=now+timedelta(minutes=schedule.interval_minutes); schedule.save(update_fields=['last_run_at','next_run_at','updated_at'])
                self.stdout.write(self.style.SUCCESS(f'Integration #{schedule.connection.id} {schedule.connection.provider}: {result}')); count+=1
            except Exception as exc:
                schedule.connection.status='attention'; schedule.connection.save(update_fields=['status','updated_at'])
                schedule.next_run_at=now+timedelta(minutes=min(schedule.interval_minutes,360)); schedule.save(update_fields=['next_run_at','updated_at'])
                self.stderr.write(f'Integration #{schedule.connection.id} failed: {exc}')
        self.stdout.write(f'Processed {count} integration schedule(s).')
