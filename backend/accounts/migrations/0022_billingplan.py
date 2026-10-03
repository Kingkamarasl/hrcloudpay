# Generated manually to add BillingPlan and backfill from current constants.
from decimal import Decimal
from django.db import migrations, models


def backfill_billing_plans(apps, schema_editor):
    BillingPlan = apps.get_model('accounts', 'BillingPlan')
    # Import constants at runtime to stay in sync
    from accounts import billing, models as acc_models
    AI_PLANS = set(getattr(billing, 'AI_PLANS', {'professional','scale','enterprise'}))
    PLAN_PRICES = getattr(billing, 'PLAN_PRICES', {})
    PLAN_USER_LIMITS = getattr(billing, 'PLAN_USER_LIMITS', {})
    PLAN_EMPLOYEE_LIMITS = getattr(acc_models, 'PLAN_EMPLOYEE_LIMITS', {})
    PLAN_LABELS = getattr(billing, 'PLAN_LABELS', {})
    order = ['starter','business','professional','scale','enterprise']
    for i, pid in enumerate(order):
        BillingPlan.objects.update_or_create(
            plan=pid,
            defaults={
                'name': PLAN_LABELS.get(pid, pid.title()),
                'monthly_price': Decimal(str(PLAN_PRICES.get(pid, 0))),
                'annual_price': Decimal(str(PLAN_PRICES.get(pid, 0))) * Decimal('10'),
                'employee_limit': PLAN_EMPLOYEE_LIMITS.get(pid),
                'user_limit': PLAN_USER_LIMITS.get(pid),
                'ai_enabled': pid in AI_PLANS,
                'highlight': pid == 'professional',
                'active': True,
                'order': i,
            },
        )


def reverse_backfill(apps, schema_editor):
    BillingPlan = apps.get_model('accounts', 'BillingPlan')
    BillingPlan.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [('accounts', '0021_pricing_plans')]

    operations = [
        migrations.CreateModel(
            name='BillingPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plan', models.CharField(choices=[('starter','Starter'),('business','Business'),('professional','Professional'),('scale','Scale'),('enterprise','Enterprise')], max_length=20, unique=True)),
                ('name', models.CharField(max_length=60)),
                ('monthly_price', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('annual_price', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('employee_limit', models.IntegerField(blank=True, null=True)),
                ('user_limit', models.IntegerField(blank=True, null=True)),
                ('ai_enabled', models.BooleanField(default=False)),
                ('highlight', models.BooleanField(default=False)),
                ('active', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['order', 'id']},
        ),
        migrations.RunPython(backfill_billing_plans, reverse_backfill),
    ]