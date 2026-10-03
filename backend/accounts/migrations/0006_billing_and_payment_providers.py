from django.db import migrations, models
import django.db.models.deletion


def seed_trial_dates(apps, schema_editor):
    from django.utils import timezone
    from datetime import timedelta
    Subscription = apps.get_model('accounts', 'Subscription')
    Company = apps.get_model('accounts', 'Company')
    now = timezone.now()
    for company in Company.objects.all():
        sub, _ = Subscription.objects.get_or_create(company=company, defaults={'status':'trial', 'currency':'USD'})
        if not sub.trial_ends_at:
            sub.started_at = sub.started_at or now
            sub.trial_ends_at = now + timedelta(days=14)
            sub.save(update_fields=['started_at','trial_ends_at'])

class Migration(migrations.Migration):
    dependencies = [('accounts','0005_tamper_evident_audit')]
    operations = [
        migrations.AddField(model_name='subscription', name='trial_ends_at', field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='subscription', name='grace_ends_at', field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='subscription', name='provider', field=models.CharField(choices=[('manual','Manual'),('flutterwave','Flutterwave'),('paystack','Paystack'),('stripe','Stripe')],default='manual',max_length=20)),
        migrations.AddField(model_name='subscription', name='provider_plan_id', field=models.CharField(blank=True,max_length=150)),
        migrations.CreateModel(
            name='PaymentProviderConfig',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('provider',models.CharField(choices=[('flutterwave','Flutterwave'),('paystack','Paystack'),('stripe','Stripe')],max_length=30,unique=True)),
                ('enabled',models.BooleanField(default=False)),
                ('public_key',models.CharField(blank=True,max_length=255)),
                ('encrypted_secret_key',models.TextField(blank=True)),
                ('webhook_secret',models.TextField(blank=True)),
                ('environment',models.CharField(choices=[('test','Test'),('live','Live')],default='test',max_length=10)),
                ('configured_at',models.DateTimeField(blank=True,null=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
            ],
            options={'ordering':['provider']},
        ),
        migrations.CreateModel(
            name='PaymentEvent',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('provider',models.CharField(max_length=30)),
                ('event_id',models.CharField(max_length=180,unique=True)),
                ('event_type',models.CharField(blank=True,max_length=120)),
                ('status',models.CharField(default='received',max_length=20)),
                ('payload',models.JSONField(blank=True,default=dict)),
                ('received_at',models.DateTimeField(auto_now_add=True)),
            ], options={'ordering':['-received_at']},
        ),
        migrations.RunPython(seed_trial_dates, migrations.RunPython.noop),
    ]
