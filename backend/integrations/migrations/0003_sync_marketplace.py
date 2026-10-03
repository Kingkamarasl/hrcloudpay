from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('integrations','0002_oauth_sync')]
    operations=[
        migrations.AddField(model_name='integrationconnection', name='environment', field=models.CharField(choices=[('sandbox','Sandbox'),('production','Production')], default='production', max_length=20)),
        migrations.CreateModel(
            name='AccountingMapping',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('payroll_expense_account_id',models.CharField(max_length=255,blank=True)),
                ('payroll_liability_account_id',models.CharField(max_length=255,blank=True)),
                ('net_pay_account_id',models.CharField(max_length=255,blank=True)),
                ('employer_contribution_account_id',models.CharField(max_length=255,blank=True)),
                ('metadata',models.JSONField(default=dict,blank=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('connection',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='accounting_mapping',to='integrations.integrationconnection')),
            ],
        ),
        migrations.CreateModel(
            name='SyncSchedule',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('enabled',models.BooleanField(default=False)),
                ('interval_minutes',models.PositiveIntegerField(default=1440)),
                ('next_run_at',models.DateTimeField(null=True,blank=True)),
                ('last_run_at',models.DateTimeField(null=True,blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('connection',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='sync_schedule',to='integrations.integrationconnection')),
            ],
        ),
        migrations.CreateModel(
            name='SyncEvent',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('provider_event_id',models.CharField(max_length=255,blank=True)),
                ('event_type',models.CharField(max_length=120)),
                ('entity_type',models.CharField(max_length=80,blank=True)),
                ('external_id',models.CharField(max_length=255,blank=True)),
                ('payload',models.JSONField(default=dict,blank=True)),
                ('processed',models.BooleanField(default=False)),
                ('processed_at',models.DateTimeField(null=True,blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('connection',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='sync_events',to='integrations.integrationconnection')),
            ],
            options={'ordering':['-created_at']},
        ),
        migrations.CreateModel(
            name='SyncConflict',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('entity_type',models.CharField(max_length=80)),
                ('external_id',models.CharField(max_length=255)),
                ('local_object_type',models.CharField(max_length=100,blank=True)),
                ('local_object_id',models.PositiveBigIntegerField(null=True,blank=True)),
                ('resolution',models.CharField(choices=[('pending','Pending'),('external','Use external'),('local','Keep HRCloudPay'),('merged','Merged')],default='pending',max_length=20)),
                ('external_data',models.JSONField(default=dict,blank=True)),
                ('local_data',models.JSONField(default=dict,blank=True)),
                ('resolved_at',models.DateTimeField(null=True,blank=True)),
                ('resolved_by',models.ForeignKey(null=True,blank=True,on_delete=django.db.models.deletion.SET_NULL,to='accounts.user')),
                ('connection',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='sync_conflicts',to='integrations.integrationconnection')),
                ('created_at',models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering':['-created_at']},
        ),
    ]
